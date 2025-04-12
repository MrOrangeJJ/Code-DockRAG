#!/usr/bin/env python3
"""
api.py - 提供代码库搜索功能的REST API
"""

import os
import sys
import logging
import json
import shutil
import zipfile
import asyncio  # 确保导入asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, WebSocket, WebSocketDisconnect, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware  # 添加CORS中间件
from pydantic import BaseModel
import uvicorn
import asyncio
from collections import defaultdict
import time
from threading import Lock
import uuid
from datetime import datetime
from dotenv import load_dotenv

# 导入系统内部模块
import lancedb
from code_dock.search_app import setup_database, generate_context
from code_dock.indexer import index_codebase
from code_dock.treesitter import generate_project_structure, generate_codebase_ast_structure
from code_dock.strong_search_agent import (
    run_agent, 
    set_trace_processors, 
    set_tracing_disabled, 
    global_ws_processor, 
    global_file_processor
)
from code_dock.treesitter import dict_to_readable_tree
import code_dock.create_tables as create_tables

# 导入共享的常量和工具函数
from code_dock.constants import RECOGNIZABLE_FILES
from code_dock.utils import (
    CODEBASE_CONFIG, 
    get_codebase_path, 
    is_valid_codebase, 
    read_file_safely, 
    init_config_file, 
    update_config_file,
    load_config_file,
    search_text
)


# 加载环境变量
load_dotenv()


# 配置API日志
log_path = os.getenv("LOG_PATH", "logs")
os.makedirs(log_path, exist_ok=True)

codebase_path = os.getenv("CODEBASE_PATH", "codebases")
os.makedirs(codebase_path, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[logging.FileHandler(os.path.join(log_path, "api.log"), encoding="utf-8"),
                            logging.StreamHandler()])
logger = logging.getLogger("SearchAPI")

# 修改日志级别为WARNING以减少输出
# 如需更详细的日志，可以将此行注释掉或改回INFO
logger.setLevel(logging.WARNING)

# 根据环境变量配置codebase_path，但不自动创建
codebase_path = os.getenv("CODEBASE_PATH", "codebases")
# 不再自动创建目录

# API端口
API_PORT = int(os.getenv("API_PORT", "30089"))


app = FastAPI(
    title="Code Dock Search API",
    description="提供基于RAG的代码库搜索功能",
    version="1.0.0"
)

# 索引状态追踪
class IndexingStatus:
    def __init__(self):
        self.status = {}
        self.lock = Lock()
    
    def set_indexing(self, codebase_name):
        with self.lock:
            self.status[codebase_name] = "indexing"
        # update_config_file(codebase_name, {"indexing_status": "indexing"})

    def set_completed(self, codebase_name):
        with self.lock:
            self.status[codebase_name] = "completed"
        # update_config_file(codebase_name, {"indexing_status": "completed"})
    
    def set_failed(self, codebase_name):
        with self.lock:
            self.status[codebase_name] = "failed"
        # update_config_file(codebase_name, {"indexing_status": "failed"})
    
    def get_status(self, codebase_name):
        with self.lock:
            return self.status.get(codebase_name, "failed")
        # return load_config_file(codebase_name, "indexing_status")
    
    def is_indexing(self, codebase_name):
        with self.lock:
            return self.status.get(codebase_name, "failed") == "indexing"
        # return load_config_file(codebase_name, "indexing_status") == "indexing"

# 创建索引状态跟踪器实例
indexing_tracker = IndexingStatus()

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有源访问，生产环境应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# WebSocket连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.messages: Dict[str, List[Dict[str, Any]]] = {}
        self.lock = Lock()

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        with self.lock:
            self.active_connections[client_id] = websocket
            self.messages[client_id] = []

    def disconnect(self, client_id: str):
        with self.lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]
            if client_id in self.messages:
                del self.messages[client_id]

    async def send_log(self, client_id: str, message: str, level: str = "info"):
        """发送日志消息"""
        if client_id in self.active_connections:
            data = {
                "type": "log",
                "level": level,
                "message": message,
                "timestamp": time.time()
            }
            with self.lock:
                self.messages[client_id].append(data)
            await self.active_connections[client_id].send_json(data)

    async def send_progress(self, client_id: str, progress: float, status: str = ""):
        """发送进度信息"""
        if client_id in self.active_connections:
            data = {
                "type": "progress",
                "progress": progress,
                "status": status,
                "timestamp": time.time()
            }
            with self.lock:
                self.messages[client_id].append(data)
            await self.active_connections[client_id].send_json(data)

    async def send_result(self, client_id: str, result: Dict[str, Any]):
        """发送最终结果"""
        if client_id in self.active_connections:
            # 确保项目结构存在
            if "project_structure" not in result:
                # 如果项目结构不存在，添加空字典
                result["project_structure"] = {}
                logger.warning(f"结果中缺少项目结构，已添加空字典: {client_id}")
            
            data = {
                "type": "result",
                "result": result,
                "timestamp": time.time()
            }
            with self.lock:
                self.messages[client_id].append(data)
            await self.active_connections[client_id].send_json(data)

    async def send_error(self, client_id: str, error: str):
        """发送错误信息"""
        if client_id in self.active_connections:
            data = {
                "type": "error",
                "error": error,
                "timestamp": time.time()
            }
            with self.lock:
                self.messages[client_id].append(data)
            await self.active_connections[client_id].send_json(data)

    def get_messages(self, client_id: str) -> List[Dict[str, Any]]:
        """获取客户端的所有消息"""
        with self.lock:
            return self.messages.get(client_id, []).copy()

# 创建连接管理器实例
manager = ConnectionManager()


# 强力搜索类（带日志输出）
class StrongSearchAgent:
    def __init__(self, codebase_name: str, client_id: str, manager: ConnectionManager):
        self.codebase_name = codebase_name
        self.client_id = client_id
        self.manager = manager
        self.paths = get_codebase_path(codebase_name)
        self.code_path = self.paths["code"]

    async def run_search(self, query: str):
        """运行强效搜索并返回结果，设置并清理WebSocket追踪处理器"""
        
        try:
            await self.manager.send_log(self.client_id, f"开始强效搜索: {query}", "info")
            await self.manager.send_progress(self.client_id, 0.1, "初始化搜索...")

            # --- 设置WebSocket追踪 --- 
            trace_id = None
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            try:
                # 生成唯一的trace_id
                trace_id = f"ws_{self.client_id}_{int(time.time())}"
                
                # 注册到全局WebSocket处理器
                logger.info(f"为 client {self.client_id} 注册 WebSocket 追踪...")
                global_ws_processor.register(trace_id, self.client_id, self.manager)
                logger.info(f"已为客户端 {self.client_id} 启用 WebSocket 追踪，trace_id: {trace_id}")
                await self.manager.send_log(self.client_id, "Agent追踪已启用", "debug")

            except ImportError as e:
                logger.warning(f"无法导入追踪组件: {e}，但搜索仍会继续")
                await self.manager.send_log(self.client_id, "追踪组件不可用，但搜索仍会继续", "warning")
                trace_id = None
            except Exception as setup_err:
                logger.error(f"设置 WebSocket 追踪时出错: {setup_err}")
                await self.manager.send_log(self.client_id, f"设置追踪失败: {setup_err}，但搜索仍会继续", "warning")
                trace_id = None

            # 记录开始时间
            start_time = time.time()

            # 发送进度更新
            await self.manager.send_log(self.client_id, "运行Agent...", "info")
            await self.manager.send_progress(self.client_id, 0.2, "运行Agent...")


            # 运行代理，使用环境变量中的模型名称并传递trace_id
            result = await run_agent(self.codebase_name, query, trace_id=trace_id)

            # 计算执行时间
            execution_time = time.time() - start_time
            result["execution_time"] = execution_time

            result["project_structure"] = {
                "text_tree": dict_to_readable_tree(self.codebase_name)
            }

            # 发送完成消息
            await self.manager.send_log(
                self.client_id,
                f"搜索完成! 处理时间: {execution_time:.2f}秒, 发现 {len(result.get('relevant_files', []))} 个相关文件",
                "success"
            )
            await self.manager.send_progress(self.client_id, 1.0, "搜索完成!")

            # 发送结果
            await self.manager.send_result(self.client_id, result)

            return result
        except Exception as e:
            error_msg = f"强效搜索过程中出错: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await self.manager.send_log(self.client_id, error_msg, "error")
            await self.manager.send_error(self.client_id, error_msg)
            # Ensure result is defined even in case of early error
            return {"answer": f"搜索出错: {error_msg}", "relevant_files": [], "execution_time": 0}
        finally:
            # --- 清理追踪设置 --- 
            if trace_id:
                try:
                    # 从全局处理器中注销
                    logger.info(f"为 client {self.client_id} 注销 WebSocket 追踪...")
                    global_ws_processor.unregister(trace_id)
                    logger.info(f"已为客户端 {self.client_id} 禁用 WebSocket 追踪")
                except Exception as e:
                    logger.error(f"注销 WebSocket 追踪时出错 for {self.client_id}: {e}")
            # -----------------------

# --- Pydantic 模型定义 ---
class SearchRequest(BaseModel):
    codebase_name: str  # 使用代码库名称而不是路径
    query: str
    rerank: bool = False

class StrongSearchRequest(BaseModel):
    codebase_name: str  # 使用代码库名称
    query: str

class StrongSearchResponse(BaseModel):
    """强效搜索响应模型"""
    query: str
    answer: str
    project_structure: Dict[str, Any]
    relevant_files: List[str]
    file_contents: Dict[str, str]

class FileInfo(BaseModel):
    file_path: str
    content: str
    matched_functions: List[str] = []
    matched_classes: List[str] = []

class SearchResponse(BaseModel):
    query: str
    files: List[FileInfo]

class CodebaseInfo(BaseModel):
    name: str
    code_path: str
    database_path: str
    processed_path: str
    indexed: bool
    indexing_status: Optional[str] = None  # "indexing", "completed", "failed" 或 None,
    analyzer_ready: bool
    analyzer_progress: float

class ASTResponse(BaseModel):
    """AST树响应模型"""
    codebase_name: str
    structure: Dict[str, Any]

class ReferenceResponse(BaseModel):
    """符号引用查找响应模型"""
    status: str  # 操作状态: "success", "failed", "warning"
    message: str  # 状态消息或错误信息
    file_path: str  # 输入的文件路径
    result: List[Dict[str, Any]]  # 找到的引用列表

class FileContentBatchRequest(BaseModel):
    """批量获取文件内容的请求模型"""
    file_paths: List[str]

class FileContentBatchResponse(BaseModel):
    """批量获取文件内容的响应模型"""
    contents: Dict[str, str] # 键是文件相对路径，值是内容或错误信息

class ReferenceRequest(BaseModel):
    """符号引用查找请求模型"""
    file_path: str  # 符号所在的文件路径
    symbol_name: str  # 要查找引用的符号名称

class EnvSettingsRequest(BaseModel):
    """环境变量设置请求模型"""
    model_name: Optional[str] = None
    model_base_url: Optional[str] = None
    model_api_key: Optional[str] = None
    strong_search_max_turns: Optional[int] = None


def is_codebase_indexed(codebase_name: str) -> bool:
    """检查代码库是否已索引"""
    paths = get_codebase_path(codebase_name)
    db_path = paths["database"]
    
    # 检查数据库目录是否存在
    if not os.path.exists(db_path):
        logger.warning(f"数据库目录不存在: {db_path}")
        return False
        
    # 检查数据库文件是否存在
    try:
        # 直接连接到代码库特定的数据库目录
        db = lancedb.connect(db_path)
        
        # 检查表是否存在
        table_names = db.table_names()
        method_table_exists = f"{codebase_name}_method" in table_names
        class_table_exists = f"{codebase_name}_class" in table_names


        return method_table_exists and class_table_exists
            
    except ImportError:
         logger.error("lancedb 未安装")
         return False
    except Exception as e:
        logger.error(f"检查索引状态时出错 ({db_path}): {e}")
        return False

def get_codebases() -> List[CodebaseInfo]:
    """获取所有已上传的代码库信息"""
    codebases = []
    
    # 遍历codebases目录
    for codebase_dir in Path(codebase_path).iterdir():
        if codebase_dir.is_dir():
            name = codebase_dir.name
            paths = get_codebase_path(name)
            
            # 先获取索引状态，确保实时反映当前状态
            indexing_status = indexing_tracker.get_status(name)
            analyzer_ready = load_config_file(name, "analyzer_ready")
            if not analyzer_ready:
                analyzer_ready = False
            
            if indexing_status != "indexing":
                indexed = is_codebase_indexed(name)
            else:
                indexed = False

            
            analyzer_progress = load_config_file(name, "analyzer_progress")
            if not analyzer_progress:
                analyzer_progress = 0.0
            
            
            codebases.append(CodebaseInfo(
                name=name,
                code_path=paths["code"],
                database_path=paths["database"],
                processed_path=paths["processed"],
                indexed=indexed,
                indexing_status=indexing_status,
                analyzer_ready=analyzer_ready,
                analyzer_progress=analyzer_progress
            ))
    
    return codebases

def read_file_content(file_path: str) -> str:
    """读取文件内容"""
    return read_file_safely(file_path)

def setup_database_connection(codebase_name: str):
    """设置数据库连接"""
    paths = get_codebase_path(codebase_name)
    
    try:
        # 使用代码库的database目录
        method_table, class_table = setup_database(paths["code"], db_path=paths["database"])
        return method_table, class_table
    except ImportError as e:
        logger.error(f"导入setup_database失败: {e}")
        raise HTTPException(status_code=500, detail="系统错误: 无法加载搜索模块")
    except Exception as e:
        logger.error(f"设置数据库连接时出错: {e}")
        raise HTTPException(status_code=500, detail=f"连接数据库时出错: {str(e)}")

def generate_search_context(query: str, codebase_name: str, rerank: bool):
    """生成搜索上下文"""
    # 设置数据库连接
    method_table, class_table = setup_database_connection(codebase_name)
    
    try:
        # 生成上下文
        context_data = generate_context(query, method_table, class_table, rerank, codebase_name)
        # --- 简化日志输出 ---
        methods_count = len(context_data.get('methods', []))
        classes_count = len(context_data.get('classes', []))
        logger.info(f"搜索结果统计: 找到 {methods_count} 个方法, {classes_count} 个类")
        # --------------- 
        return context_data
    except ImportError as e:
        logger.error(f"导入generate_context失败: {e}")
        raise HTTPException(status_code=500, detail="系统错误: 无法加载搜索模块")
    except Exception as e:
        logger.error(f"生成搜索上下文时出错: {e}")
        raise HTTPException(status_code=500, detail=f"生成搜索上下文时出错: {str(e)}")

async def run_strong_search(codebase_name: str, query: str, trace_id: str = None) -> Dict[str, Any]:
    """运行强效搜索代理 (不处理追踪)"""
    # 获取代码库路径
    paths = get_codebase_path(codebase_name)
    code_path = paths["code"]
    
    try:
        # 运行搜索代理
        logger.info(f"启动强效搜索代理: codebase={codebase_name}, query='{query}'")
        start_time = asyncio.get_event_loop().time()
        
        # 运行代理并获取结果 - 使用环境变量中的模型，并传递trace_id
        result = await run_agent(codebase_name, query, trace_id=trace_id)
        
        # 计算执行时间
        execution_time = asyncio.get_event_loop().time() - start_time
        
        # 添加执行时间到结果
        result["execution_time"] = execution_time
        raw_structure = generate_project_structure(codebase_name)
        result["project_structure"] = raw_structure
        
        return result
    except ImportError as e:
        logger.error(f"导入相关模块失败: {e}")
        raise HTTPException(status_code=500, detail="系统错误: 无法加载强效搜索模块")
    except Exception as e:
        logger.error(f"运行强效搜索代理时出错: {e}")
        raise HTTPException(status_code=500, detail=f"运行强效搜索时出错: {str(e)}")

# --- 全局初始化事件 ---
@app.on_event("startup")
async def startup_event():
    """服务器启动时执行初始化和全局注册"""
    logger.info("正在执行API服务器启动初始化...")
    
    # 清空所有可能残留的处理器
    try:
        set_trace_processors([])
        logger.info("已清空所有残留的追踪处理器")
    except Exception as e:
        logger.error(f"清空追踪处理器时出错: {e}")
    
    # 设置全局追踪处理器
    set_trace_processors([global_ws_processor, global_file_processor])
    set_tracing_disabled(False)
    logger.info("已注册全局追踪处理器")
    
    # 确保嵌入向量生成器全局注册
    try:
        # 导入自定义嵌入类并触发注册
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))

    except Exception as e:
        logger.error(f"初始化全局注册时出错: {e}")
        # 记录错误但允许服务器继续启动


def reset_indexed_status(codebase_name: str):
    """重置代码库的索引状态，删除数据库和处理文件夹"""
    paths = get_codebase_path(codebase_name)
    db_dir = Path(paths["database"])
    proc_dir = Path(paths["processed"])
    
    # 如果当前正在索引，拒绝重置
    if indexing_tracker.is_indexing(codebase_name):
        logger.warning(f"代码库 '{codebase_name}' 正在索引中，无法重置索引状态")
        return False
    
    # 删除数据库目录
    if db_dir.exists():
        try:
            shutil.rmtree(db_dir)
            logger.info(f"已删除数据库目录: {db_dir}")
            # 重新创建空目录
            db_dir.mkdir(exist_ok=True)
        except Exception as e:
            logger.error(f"删除数据库目录 {db_dir} 时出错: {e}")
    
    # 删除处理文件夹
    if proc_dir.exists():
        try:
            shutil.rmtree(proc_dir)
            logger.info(f"已删除处理目录: {proc_dir}")
            # 重新创建空目录
            proc_dir.mkdir(exist_ok=True)
        except Exception as e:
            logger.error(f"删除处理目录 {proc_dir} 时出错: {e}")
    
            
    return True

# --- API 端点定义 ---

@app.get("/")
def read_root():
    """根路径，用于健康检查"""
    return {"message": "Code Dock Search API is running"}

@app.get("/codebases", response_model=List[CodebaseInfo])
async def list_all_codebases():
    """列出所有代码库（包括未索引的）"""
    return get_codebases()

@app.get("/codebases/indexed", response_model=List[CodebaseInfo])
async def list_indexed_codebases():
    """列出所有已成功索引的代码库"""
    all_codebases = get_codebases()
    indexed_codebases = [cb for cb in all_codebases if cb.indexed]
    return indexed_codebases

# @app.post("/upload")
# async def upload_codebase(
#     codebase_name: str = Form(...),
#     file: UploadFile = File(...)
# ):
#     """处理代码库上传、解压，但不执行索引"""
#     if not file.filename or not file.filename.endswith('.zip'):
#         raise HTTPException(status_code=400, detail="请上传ZIP格式的文件")

#     if not codebase_name or not codebase_name.strip():
#         raise HTTPException(status_code=400, detail="请提供有效的代码库名称")
    
#     # 规范化代码库名称
#     safe_codebase_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in codebase_name.strip())
#     if not safe_codebase_name:
#         raise HTTPException(status_code=400, detail="代码库名称无效")

#     paths = get_codebase_path(safe_codebase_name)
#     base_dir = Path(paths["base"])
#     code_dir = Path(paths["code"])
#     db_dir = Path(paths["database"])
#     proc_dir = Path(paths["processed"])
#     upload_dir = Path("uploads")
#     zip_path = upload_dir / f"{safe_codebase_name}.zip"

#     if base_dir.exists():
#         raise HTTPException(status_code=400, detail=f"代码库 '{safe_codebase_name}' 已存在")

#     try:
#         # 创建目录
#         upload_dir.mkdir(exist_ok=True)
#         base_dir.mkdir(parents=True, exist_ok=True)
#         code_dir.mkdir(exist_ok=True)
#         db_dir.mkdir(exist_ok=True)
#         proc_dir.mkdir(exist_ok=True)

#         # 保存ZIP文件
#         logger.info(f"正在保存上传的ZIP文件到: {zip_path}")
#         with open(zip_path, "wb") as buffer:
#             shutil.copyfileobj(file.file, buffer)
#         logger.info("ZIP文件保存完成")

#         # 解压ZIP文件
#         logger.info(f"正在解压 {zip_path} 到 {code_dir}...")
#         with zipfile.ZipFile(zip_path, 'r') as zip_ref:
#             zip_ref.extractall(code_dir)
#         logger.info("解压完成")
        
#         # 解压后删除ZIP文件
#         if zip_path.exists():
#             zip_path.unlink()
#             logger.info(f"已删除ZIP文件: {zip_path}")

#         # 检查是否是有效的代码库
#         is_valid = is_valid_codebase(str(code_dir))
#         if not is_valid:
#             # 清理已创建的文件
#             shutil.rmtree(base_dir)
#             raise HTTPException(
#                 status_code=400, 
#                 detail="未能识别为有效的代码库，未找到常见的项目文件。请上传包含代码的ZIP文件。"
#             )
#         else:
#             init_config_file(safe_codebase_name)      
#         # 返回信息，但不执行索引
#         return JSONResponse(content={
#             "codebase_name": safe_codebase_name,
#             "message": f"代码库上传和解压成功，请手动点击索引按钮开始索引过程",
#             "indexed": False,
#             "valid": True
#         })

#     except HTTPException:
#         # 直接将HTTPException往上抛
#         raise
#     except Exception as e:
#         logger.error(f"上传或处理代码库 '{safe_codebase_name}' 时出错: {e}", exc_info=True)
#         # 清理可能已创建的文件/目录
#         if base_dir.exists():
#             try:
#                 shutil.rmtree(base_dir)
#             except Exception as cleanup_e:
#                 logger.error(f"清理目录 {base_dir} 失败: {cleanup_e}")
#         if zip_path.exists():
#             try:
#                 zip_path.unlink()
#             except Exception as cleanup_e:
#                 logger.error(f"清理ZIP文件 {zip_path} 失败: {cleanup_e}")
#         raise HTTPException(status_code=500, detail=f"处理上传文件时出错: {str(e)}")

# 新API端点
@app.post("/codebases")
async def create_codebase(
    name: str = Form(...),
    file: UploadFile = File(...)
):
    """处理代码库上传、解压，但不执行索引 - 新版API"""
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传ZIP格式的文件")

    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="请提供有效的代码库名称")
    
    # 规范化代码库名称
    safe_codebase_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.strip())
    if not safe_codebase_name:
        raise HTTPException(status_code=400, detail="代码库名称无效")

    paths = get_codebase_path(safe_codebase_name)
    base_dir = Path(paths["base"])
    code_dir = Path(paths["code"])
    db_dir = Path(paths["database"])
    proc_dir = Path(paths["processed"])
    upload_dir = Path("uploads")
    zip_path = upload_dir / f"{safe_codebase_name}.zip"

    if base_dir.exists():
        raise HTTPException(status_code=400, detail=f"代码库 '{safe_codebase_name}' 已存在")

    try:
        # 创建目录
        upload_dir.mkdir(exist_ok=True)
        base_dir.mkdir(parents=True, exist_ok=True)
        code_dir.mkdir(exist_ok=True)
        db_dir.mkdir(exist_ok=True)
        proc_dir.mkdir(exist_ok=True)

        # 保存ZIP文件
        logger.info(f"正在保存上传的ZIP文件到: {zip_path}")
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info("ZIP文件保存完成")

        # 解压ZIP文件
        logger.info(f"正在解压 {zip_path} 到 {code_dir}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(code_dir)
        logger.info("解压完成")
        
        # 解压后删除ZIP文件
        if zip_path.exists():
            zip_path.unlink()
            logger.info(f"已删除ZIP文件: {zip_path}")

        # 检查是否是有效的代码库
        is_valid = is_valid_codebase(str(code_dir))
        if not is_valid:
            # 清理已创建的文件
            shutil.rmtree(base_dir)
            raise HTTPException(
                status_code=400, 
                detail="未能识别为有效的代码库，未找到常见的项目文件。请上传包含代码的ZIP文件。"
            )
        else:
            init_config_file(safe_codebase_name)      
        # 返回信息，但不执行索引
        return {
            "codebase_name": safe_codebase_name,
            "message": f"代码库上传和解压成功，请手动点击索引按钮开始索引过程",
            "indexed": False,
            "valid": True
        }

    except HTTPException:
        # 直接将HTTPException往上抛
        raise
    except Exception as e:
        logger.error(f"上传或处理代码库 '{safe_codebase_name}' 时出错: {e}", exc_info=True)
        # 清理可能已创建的文件/目录
        if base_dir.exists():
            try:
                shutil.rmtree(base_dir)
            except Exception as cleanup_e:
                logger.error(f"清理目录 {base_dir} 失败: {cleanup_e}")
        if zip_path.exists():
            try:
                zip_path.unlink()
            except Exception as cleanup_e:
                logger.error(f"清理ZIP文件 {zip_path} 失败: {cleanup_e}")
        raise HTTPException(status_code=500, detail=f"处理上传文件时出错: {str(e)}")

@app.get("/codebases/{codebase_name}/ast", response_model=ASTResponse)
async def get_codebase_ast(codebase_name: str):
    """获取代码库的AST树结构"""
    # 检查代码库是否存在
    paths = get_codebase_path(codebase_name)
    
    if not os.path.exists(paths["code"]):
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    try:
        # 生成AST树结构
        ast_structure = generate_codebase_ast_structure(codebase_name)
        
        return ASTResponse(
            codebase_name=codebase_name,
            structure=ast_structure
        )
    except ImportError as e:
        logger.error(f"导入generate_codebase_ast_structure失败: {e}")
        raise HTTPException(status_code=500, detail="系统错误: 无法加载AST分析模块")
    except Exception as e:
        logger.error(f"生成AST树时出错: {e}")
        raise HTTPException(status_code=500, detail=f"生成AST树时出错: {str(e)}")

@app.post("/search", response_model=SearchResponse)
async def search_codebase(request: SearchRequest):
    """执行代码库搜索"""
    logger.info(f"接收到搜索请求: codebase='{request.codebase_name}', query='{request.query}'")
    
    # 1. 检查代码库是否存在
    codebase_name = request.codebase_name
    paths = get_codebase_path(codebase_name)
    code_path = Path(paths["code"]) # 使用 Path 对象
    
    if not code_path.exists():
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    if not is_codebase_indexed(codebase_name):
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 尚未索引")
    
    # 2. 执行搜索
    try:
        context_data = generate_search_context(request.query, codebase_name, request.rerank)
    except Exception as e:
        logger.error(f"搜索过程中出错: {e}")
        raise HTTPException(status_code=500, detail=f"搜索过程中出错: {str(e)}")

    # 3. 收集文件及其关联的函数和类
    file_symbols = defaultdict(lambda: {"functions": set(), "classes": set()})

    # 处理方法
    for method in context_data.get('methods', []):
        file_path_str = method.get('file_path', '')
        method_name = method.get('name', '')
        if file_path_str and method_name:
            try:
                relative_path = Path(file_path_str).relative_to(code_path)
                file_symbols[str(relative_path)]['functions'].add(method_name)
            except ValueError:
                logger.warning(f"无法处理方法文件路径: {file_path_str} (不是 {code_path} 的子路径)")

    # 处理类
    for class_info in context_data.get('classes', []):
        file_path_str = class_info.get('file_path', '')
        class_name = class_info.get('name', '')
        if file_path_str and class_name:
            try:
                relative_path = Path(file_path_str).relative_to(code_path)
                file_symbols[str(relative_path)]['classes'].add(class_name)
            except ValueError:
                logger.warning(f"无法处理类文件路径: {file_path_str} (不是 {code_path} 的子路径)")

    # 简化日志输出，只记录文件数量和匹配数量，不记录详细内容
    matched_files_count = len(file_symbols)
    total_functions = sum(len(symbols["functions"]) for symbols in file_symbols.values())
    total_classes = sum(len(symbols["classes"]) for symbols in file_symbols.values())
    logger.info(f"搜索结果: 匹配到 {matched_files_count} 个文件，{total_functions} 个函数，{total_classes} 个类")

    # 4. 组装 FileInfo（不读取文件内容）
    files_info = []
    for relative_file_path, symbols in file_symbols.items():
        if relative_file_path.strip():
            full_path = code_path / relative_file_path
            cont = read_file_safely(full_path)
            files_info.append(FileInfo(
                file_path=relative_file_path,
                content=cont,
                matched_functions=sorted(list(symbols["functions"])),
                matched_classes=sorted(list(symbols["classes"]))
            ))

    # 5. 返回响应
    return SearchResponse(
        query=request.query,
        files=files_info
    )

@app.post("/strong_search", response_model=StrongSearchResponse)
async def strong_search_codebase(request: StrongSearchRequest):
    """执行强效代码库搜索（基于LLM智能分析），并记录追踪信息到文件。"""
    logger.info(f"接收到强效搜索请求: codebase='{request.codebase_name}', query='{request.query}'")
    
    # 1. 检查代码库是否存在
    codebase_name = request.codebase_name
    paths = get_codebase_path(codebase_name)
    
    if not os.path.exists(paths["code"]):
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    # 创建日志目录和文件
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # 创建基于时间戳的日志文件
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"strong_search_{codebase_name}_{timestamp}.log"
    log_path = log_dir / log_filename
    
    # 设置文件日志处理器 (用于基本日志和追踪日志)
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(logging.INFO) # 确保能捕获追踪信息
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # --- 设置文件追踪 --- 
    trace_id = None
    
    # 导入所需的追踪组件和处理器
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        # 生成唯一的trace_id
        trace_id = f"api_{int(time.time())}_{str(uuid.uuid4())[:8]}"
        
        # 注册到全局文件处理器
        global_file_processor.register(trace_id, file_handler)
        logger.info(f"已为本次API请求启用文件追踪日志记录，trace_id: {trace_id}")

    except ImportError as import_err:
        logger.warning(f"无法导入追踪组件: {import_err}，但搜索仍会继续")
    except Exception as trace_setup_e:
        logger.error(f"设置追踪处理器时出错: {trace_setup_e}，但搜索仍会继续")
    # ---------------------
    
    result = None
    try:
        # 运行强效搜索，传递trace_id
        result = await run_strong_search(codebase_name, request.query, trace_id=trace_id)

        contents = {}
        
        for file_path in result["relevant_files"]:
            full_path = Path(paths["code"]) / file_path
            try:
                contents[file_path] = read_file_safely(full_path)
            except Exception as e:
                pass

        # 3. 返回响应
        return StrongSearchResponse(
            query=request.query,
            answer=result["answer"],
            relevant_files=result["relevant_files"],
            project_structure={},
            file_contents=contents
        )
    except Exception as e:
        logger.error(f"强效搜索过程中出错: {e}", exc_info=True)
        # 确保错误也被记录到文件
        logger.addHandler(file_handler)
        logger.error(f"搜索过程中出错: {str(e)}", exc_info=True)
        logger.removeHandler(file_handler)
        raise HTTPException(status_code=500, detail=f"强效搜索过程中出错: {str(e)}")
    finally:
        # --- 清理追踪设置 --- 
        if trace_id:
            try:
                logger.info("正在注销文件追踪...")
                global_file_processor.unregister(trace_id)
                logger.info("文件追踪已注销")
            except Exception as trace_cleanup_e:
                logger.error(f"注销文件追踪时出错: {trace_cleanup_e}")
        # --------------------
        
        # 关闭文件处理器
        if file_handler:
            file_handler.close()

# @app.post("/codebases/{codebase_name}/file_content_batch", response_model=FileContentBatchResponse)
# async def get_file_content_batch(codebase_name: str, request: Request):
#     """批量获取指定文件的内容"""
#     paths = get_codebase_path(codebase_name)
#     code_path = Path(paths["code"])
    
#     if not code_path.exists():
#         raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
#     # 从请求体中读取文件路径列表
#     try:
#         data = await request.json()
#         file_paths = data.get("file_paths", [])
#         if not isinstance(file_paths, list):
#             raise HTTPException(status_code=400, detail="file_paths必须是文件路径的数组")
#     except Exception as e:
#         logger.error(f"解析请求体失败: {e}", exc_info=True)
#         raise HTTPException(status_code=400, detail=f"无效的请求格式: {str(e)}")
    
#     # 批量读取文件内容
#     contents = {}
#     for file_path in file_paths:
#         full_path = code_path / file_path
        
#         # 检查路径是否在代码库目录下
#         try:
#             relative_to_code = full_path.resolve().relative_to(code_path.resolve())
#         except ValueError:
#             contents[file_path] = f"错误: 无效的文件路径 '{file_path}'"
#             continue

#         # 读取文件内容
#         try:
#             contents[file_path] = read_file_safely(full_path)
#         except Exception as e:
#             logger.error(f"读取文件 {file_path} 内容时出错: {e}", exc_info=True)
#             contents[file_path] = f"错误: 读取文件内容时出错: {str(e)}"
    
#     return {"contents": contents}

@app.post("/codebases/{codebase_name}/files/batch", response_model=FileContentBatchResponse)
async def get_files_batch(codebase_name: str, request: FileContentBatchRequest):
    """批量获取指定文件的内容 - 新版API"""
    paths = get_codebase_path(codebase_name)
    code_path = Path(paths["code"])
    
    if not code_path.exists():
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    file_paths = request.file_paths
    
    # 批量读取文件内容
    contents = {}
    for file_path in file_paths:
        full_path = code_path / file_path
        
        # 检查路径是否在代码库目录下
        try:
            relative_to_code = full_path.resolve().relative_to(code_path.resolve())
        except ValueError:
            contents[file_path] = f"错误: 无效的文件路径 '{file_path}'"
            continue

        # 读取文件内容
        try:
            contents[file_path] = read_file_safely(full_path)
        except Exception as e:
            logger.error(f"读取文件 {file_path} 内容时出错: {e}", exc_info=True)
            contents[file_path] = f"错误: 读取文件内容时出错: {str(e)}"
    
    return {"contents": contents}

@app.post("/codebases/{codebase_name}/index")
async def index_codebase_api(codebase_name: str, background_tasks: BackgroundTasks):
    """手动触发对特定代码库的索引 - 新版API"""
    paths = get_codebase_path(codebase_name)
    code_dir = Path(paths["code"])

    if not code_dir.exists() or not code_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"代码库代码目录 '{code_dir}' 不存在")
    
    # 如果当前已经在索引中，拒绝重复索引
    if indexing_tracker.is_indexing(codebase_name):
        return {
            "codebase_name": codebase_name, 
            "indexed": False, 
            "message": "该代码库正在索引中，请等待索引完成", 
            "status": "indexing"
        }

    # 设置状态为正在索引
    indexing_tracker.set_indexing(codebase_name)
    
    # 在后台任务中运行索引
    async def run_indexing_task():
        logger.info(f"开始索引代码库 '{codebase_name}'...")
        try:
            success, message = await index_codebase(str(code_dir))
            
            if success:
                logger.info(f"索引成功: {message}")
                indexing_tracker.set_completed(codebase_name)
            else:
                logger.error(f"索引失败: {message}")
                indexing_tracker.set_failed(codebase_name)
        except Exception as e:
            logger.error(f"索引过程中出错: {e}")
            indexing_tracker.set_failed(codebase_name)
    
    # 启动异步任务
    background_tasks.add_task(run_indexing_task)
    
    # 立即返回响应，但后台继续运行索引任务
    return {
        "codebase_name": codebase_name, 
        "indexed": False, 
        "message": "索引已启动，请等待索引完成", 
        "status": "indexing",
        "indexing_status": "indexing"  # 确保前端可以立即获取到正确的状态
    }

@app.delete("/codebases/{codebase_name}")
async def delete_codebase(codebase_name: str):
    """删除代码库"""
    paths = get_codebase_path(codebase_name)
    base_dir = Path(paths["base"])
    zip_path = Path("uploads") / f"{codebase_name}.zip"

    if not base_dir.exists():
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
        
    # 检查是否正在索引中，如果是则拒绝删除
    if indexing_tracker.is_indexing(codebase_name):
        raise HTTPException(status_code=400, detail=f"代码库 '{codebase_name}' 正在索引中，无法删除")

    logger.info(f"准备删除代码库: {codebase_name} (目录: {base_dir})" )
    try:
        shutil.rmtree(base_dir)
        logger.info(f"已删除目录: {base_dir}")
        if zip_path.exists():
            zip_path.unlink()
            logger.info(f"已删除ZIP文件: {zip_path}")
            
                
        return JSONResponse(content={"success": True, "message": f"代码库 '{codebase_name}' 已删除"})
    except Exception as e:
        logger.error(f"删除代码库 '{codebase_name}' 时出错: {e}", exc_info=True)
        # 即使删除失败，也可能部分成功，所以不一定需要 500
        # 可以考虑返回一个特定的错误码或消息
        raise HTTPException(status_code=500, detail=f"删除代码库时出错: {str(e)}")

@app.get("/codebases/{codebase_name}/files")
async def list_codebase_files(codebase_name: str, path: str = ""):
    """列出代码库中指定路径下的所有文件和目录"""
    paths = get_codebase_path(codebase_name)
    code_dir = Path(paths["code"])
    
    if not code_dir.exists():
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    # 构建完整的浏览路径
    browse_path = code_dir / path if path else code_dir
    
    # 检查路径是否在代码库目录下
    try:
        relative_to_code = browse_path.resolve().relative_to(code_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的路径: {path}")
    
    if not browse_path.exists():
        raise HTTPException(status_code=404, detail=f"路径 '{path}' 不存在")
    
    if not browse_path.is_dir():
        raise HTTPException(status_code=400, detail=f"路径 '{path}' 不是一个目录")
    
    try:
        # 列出所有文件和目录
        items = []
        for item in browse_path.iterdir():
            relative_path = str(item.relative_to(code_dir))
            items.append({
                "name": item.name,
                "path": relative_path,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
                "modified": item.stat().st_mtime
            })
        
        # 按类型和名称排序
        items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"]))
        
        return items
    except Exception as e:
        logger.error(f"列出文件时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"列出文件时出错: {str(e)}")

@app.get("/codebases/{codebase_name}/description")
async def get_project_description(codebase_name: str):
    try:
        paths = get_codebase_path(codebase_name)
        code_dir = Path(paths["processed"])
        if not code_dir.exists():
            raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")

        full_path = code_dir / "project_description.txt"
        with open(full_path, 'r', encoding='utf-8') as f:
            project_description = f.read().strip()
        logger.info(f"已加载{codebase_name}的项目介绍")
        return project_description
    except Exception as e:
        logger.warning(f"读取项目介绍文件时出错: {e}")
        return None



# @app.get("/codebases/{codebase_name}/file_content")
# async def get_file_content(codebase_name: str, file_path: str):
#     """获取代码库中指定文件的内容"""
#     paths = get_codebase_path(codebase_name)
#     code_dir = Path(paths["code"])
    
#     if not code_dir.exists():
#         raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
#     # 构建完整的文件路径
#     full_path = code_dir / file_path
    
#     # 检查路径是否在代码库目录下
#     try:
#         relative_to_code = full_path.resolve().relative_to(code_dir.resolve())
#     except ValueError:
#         raise HTTPException(status_code=400, detail=f"无效的文件路径: {file_path}")
    
#     if not full_path.exists():
#         raise HTTPException(status_code=404, detail=f"文件 '{file_path}' 不存在")
    
#     if not full_path.is_file():
#         raise HTTPException(status_code=400, detail=f"路径 '{file_path}' 不是一个文件")
    
#     try:
#         # 读取文件内容
#         with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
#             content = f.read()
        
#         return {"file_path": file_path, "content": content}
#     except Exception as e:
#         logger.error(f"读取文件内容时出错: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"读取文件内容时出错: {str(e)}")

# @app.post("/codebases/{codebase_name}/upload_file")
# async def upload_file(
#     codebase_name: str, 
#     file: UploadFile = File(...),
#     directory: str = Form("")
# ):
#     """向代码库中上传单个文件"""
#     paths = get_codebase_path(codebase_name)
#     code_dir = Path(paths["code"])
    
#     if not code_dir.exists():
#         raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
#     if not file.filename:
#         raise HTTPException(status_code=400, detail="无效的文件名")
    
#     # 构建目标目录路径
#     target_dir = code_dir / directory if directory else code_dir
    
#     # 检查目标目录是否在代码库目录下
#     try:
#         relative_to_code = target_dir.resolve().relative_to(code_dir.resolve())
#     except ValueError:
#         raise HTTPException(status_code=400, detail=f"无效的目标目录: {directory}")
    
#     # 确保目标目录存在
#     if not target_dir.exists():
#         try:
#             target_dir.mkdir(parents=True, exist_ok=True)
#         except Exception as e:
#             logger.error(f"创建目录 {target_dir} 时出错: {e}")
#             raise HTTPException(status_code=500, detail=f"创建目录失败: {str(e)}")
    
#     # 构建文件保存路径
#     file_path = target_dir / file.filename
#     relative_path = file_path.relative_to(code_dir)
    
#     try:
#         # 保存文件
#         with open(file_path, "wb") as buffer:
#             shutil.copyfileobj(file.file, buffer)
        
#         # 重置索引状态
#         reset_indexed_status(codebase_name)
        
#         return {
#             "success": True, 
#             "file_path": str(relative_path), 
#             "message": f"文件 '{file.filename}' 上传成功，索引状态已重置"
#         }
#     except Exception as e:
#         logger.error(f"上传文件时出错: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"上传文件时出错: {str(e)}")

# @app.delete("/codebases/{codebase_name}/file")
# async def delete_file(codebase_name: str, file_path: str):
#     """从代码库中删除单个文件"""
#     paths = get_codebase_path(codebase_name)
#     code_dir = Path(paths["code"])
    
#     if not code_dir.exists():
#         raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
#     # 构建完整的文件路径
#     full_path = code_dir / file_path
    
#     # 检查路径是否在代码库目录下
#     try:
#         relative_to_code = full_path.resolve().relative_to(code_dir.resolve())
#     except ValueError:
#         raise HTTPException(status_code=400, detail=f"无效的文件路径: {file_path}")
    
#     if not full_path.exists():
#         raise HTTPException(status_code=404, detail=f"文件 '{file_path}' 不存在")
    
#     try:
#         # 删除文件或目录
#         if full_path.is_file():
#             full_path.unlink()
#         elif full_path.is_dir():
#             shutil.rmtree(full_path)
        
#         # 重置索引状态
#         reset_indexed_status(codebase_name)
        
#         return {
#             "success": True, 
#             "file_path": file_path,
#             "message": f"{'目录' if full_path.is_dir() else '文件'} '{file_path}' 已删除，索引状态已重置"
#         }
#     except Exception as e:
#         logger.error(f"删除文件/目录时出错: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"删除操作时出错: {str(e)}")

# 新API端点
@app.delete("/codebases/{codebase_name}/files/{file_path:path}")
async def delete_file_by_path(codebase_name: str, file_path: str):
    """从代码库中删除单个文件 - 新版API"""
    paths = get_codebase_path(codebase_name)
    code_dir = Path(paths["code"])
    
    if not code_dir.exists():
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    # 构建完整的文件路径
    full_path = code_dir / file_path
    
    # 检查路径是否在代码库目录下
    try:
        relative_to_code = full_path.resolve().relative_to(code_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的文件路径: {file_path}")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"文件 '{file_path}' 不存在")
    
    try:
        # 删除文件或目录
        if full_path.is_file():
            full_path.unlink()
        elif full_path.is_dir():
            shutil.rmtree(full_path)
        
        # 重置索引状态
        reset_indexed_status(codebase_name)
        
        return {
            "success": True, 
            "file_path": file_path,
            "message": f"{'目录' if full_path.is_dir() else '文件'} '{file_path}' 已删除，索引状态已重置"
        }
    except Exception as e:
        logger.error(f"删除文件/目录时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除操作时出错: {str(e)}")

# --- WebSocket 端点 --- 

@app.websocket("/ws/strong_search/{client_id}")
async def websocket_strong_search(websocket: WebSocket, client_id: str):
    """提供实时强力搜索进度的WebSocket接口"""
    await manager.connect(websocket, client_id)
    search_task = None
    try:
        await manager.send_log(client_id, f"WebSocket连接已建立 (ID: {client_id})", "info")

        # 接收搜索参数
        data = await websocket.receive_json()
        codebase_name = data.get("codebase_name")
        query = data.get("query")

        if not codebase_name or not query:
            await manager.send_error(client_id, "缺少必要参数: codebase_name 和 query")
            await websocket.close()
            return

        # 检查代码库是否存在
        paths = get_codebase_path(codebase_name)
        if not os.path.exists(paths["code"]):
            await manager.send_error(client_id, f"代码库 '{codebase_name}' 不存在")
            await websocket.close()
            return

        # 创建搜索代理实例
        search_agent_instance = StrongSearchAgent(codebase_name, client_id, manager)

        # 异步运行搜索任务
        search_task = asyncio.create_task(search_agent_instance.run_search(query))
        receive_task = asyncio.create_task(websocket.receive_text())

        # 等待任务完成或客户端断开
        done, pending = await asyncio.wait(
            [search_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # 取消所有未完成的任务
        for task in pending:
            task.cancel()
        
        # 等待被取消的任务完成，忽略取消异常
        if pending:
            try:
                await asyncio.gather(*pending, return_exceptions=True)
            except Exception:
                pass
        
        # 如果搜索任务先完成，获取结果
        if search_task in done:
             result = await search_task
             logger.info(f"Search task for {client_id} completed.")
        else:
            await manager.send_log(client_id, "客户端断开或发送消息，取消搜索...", "warning")
            logger.info(f"Client {client_id} disconnected or sent message, cancelling search.")

    except WebSocketDisconnect:
        logger.info(f"客户端断开连接: {client_id}")
        if search_task and not search_task.done():
            search_task.cancel()
            # 等待搜索任务取消完成，这会触发StrongSearchAgent中的finally块
            try:
                await search_task
            except asyncio.CancelledError:
                pass
            await manager.send_log(client_id, "客户端断开连接，取消搜索...", "warning")
    except asyncio.CancelledError:
        logger.info(f"Search task for {client_id} was cancelled.")
    except Exception as e:
        error_msg = f"WebSocket处理出错: {str(e)}"
        logger.error(error_msg, exc_info=True)
        try:
            await manager.send_error(client_id, error_msg)
        except Exception as send_err:
            logger.error(f"Failed to send error to client {client_id}: {send_err}")
    finally:
        if search_task and not search_task.done():
            search_task.cancel()
            # 确保任务完全取消
            try:
                await search_task
            except asyncio.CancelledError:
                pass
        manager.disconnect(client_id)
        logger.info(f"Cleaned up connection for client: {client_id}")


@app.get("/strong_search/new_client_id")
async def generate_client_id():
    """生成新的客户端ID用于WebSocket连接"""
    client_id = str(uuid.uuid4())
    return {"client_id": client_id}


# 新API端点
@app.post("/codebases/{codebase_name}/references/find", response_model=ReferenceResponse)
async def find_references(
    codebase_name: str,
    request: ReferenceRequest
):
    """查找代码中的符号引用 - 新版API"""
    # 检查代码库是否存在
    paths = get_codebase_path(codebase_name)
    if not os.path.exists(paths["code"]):
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    # 检查分析器是否就绪
    analyzer_ready = load_config_file(codebase_name, "analyzer_ready")
    if not analyzer_ready:
        raise HTTPException(status_code=400, detail=f"代码库 '{codebase_name}' 未完成分析器初始化，无法查找引用")
    
    try:

        
        # 创建搜索代理实例
        from code_dock.strong_search_agent import StrongSearchAgent
        agent = StrongSearchAgent(codebase_name)
        
        # 调用find_references方法
        result = await agent.find_references(request.file_path, request.symbol_name)
        return result
    except Exception as e:
        logger.error(f"查找代码引用时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查找代码引用时出错: {str(e)}")

# 添加获取文件内容的API端点
@app.get("/codebases/{codebase_name}/files/{file_path:path}")
async def get_file_content_by_path(codebase_name: str, file_path: str):
    """获取代码库中指定文件的内容 - 新版API"""
    paths = get_codebase_path(codebase_name)
    code_dir = Path(paths["code"])
    
    if not code_dir.exists():
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    # 构建完整的文件路径
    full_path = code_dir / file_path
    
    # 检查路径是否在代码库目录下
    try:
        relative_to_code = full_path.resolve().relative_to(code_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的文件路径: {file_path}")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"文件 '{file_path}' 不存在")
    
    if not full_path.is_file():
        raise HTTPException(status_code=400, detail=f"路径 '{file_path}' 不是一个文件")
    
    try:
        # 读取文件内容
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        return {"file_path": file_path, "content": content}
    except Exception as e:
        logger.error(f"读取文件内容时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取文件内容时出错: {str(e)}")

# 添加上传文件的API端点
@app.post("/codebases/{codebase_name}/files")
async def upload_file_to_codebase(
    codebase_name: str, 
    file: UploadFile = File(...),
    directory: str = Form("")
):
    """向代码库中上传单个文件 - 新版API"""
    paths = get_codebase_path(codebase_name)
    code_dir = Path(paths["code"])
    
    if not code_dir.exists():
        raise HTTPException(status_code=404, detail=f"代码库 '{codebase_name}' 不存在")
    
    if not file.filename:
        raise HTTPException(status_code=400, detail="无效的文件名")
    
    # 构建目标目录路径
    target_dir = code_dir / directory if directory else code_dir
    
    # 检查目标目录是否在代码库目录下
    try:
        relative_to_code = target_dir.resolve().relative_to(code_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的目标目录: {directory}")
    
    # 确保目标目录存在
    if not target_dir.exists():
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"创建目录 {target_dir} 时出错: {e}")
            raise HTTPException(status_code=500, detail=f"创建目录失败: {str(e)}")
    
    # 构建文件保存路径
    file_path = target_dir / file.filename
    relative_path = file_path.relative_to(code_dir)
    
    try:
        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 重置索引状态
        reset_indexed_status(codebase_name)
        
        return {
            "success": True, 
            "file_path": str(relative_path), 
            "message": f"文件 '{file.filename}' 上传成功，索引状态已重置"
        }
    except Exception as e:
        logger.error(f"上传文件时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传文件时出错: {str(e)}")

# 新API端点
@app.get("/codebases/{codebase_name}/search/text")
async def search_text_in_codebase(codebase_name: str, keyword: str):
    """在代码库中搜索关键词，返回匹配的文件路径列表"""

    result = search_text(codebase_name, keyword)
    return result

@app.post("/settings/env")
async def update_env_settings(request: EnvSettingsRequest):
    """更新强化搜索相关的环境变量设置"""
    try:
        # 创建一个字典来跟踪哪些变量被更新了
        updated = {}
        
        # 只更新请求中提供的非None值
        if request.model_name is not None:
            os.environ["MODEL_NAME"] = request.model_name
            updated["MODEL_NAME"] = request.model_name
            
        if request.model_base_url is not None:
            os.environ["MODEL_BASE_URL"] = request.model_base_url
            updated["MODEL_BASE_URL"] = request.model_base_url
            
        if request.model_api_key is not None:
            os.environ["MODEL_API_KEY"] = request.model_api_key
            updated["MODEL_API_KEY"] = "**********"  # 出于安全考虑不返回实际密钥
            
        if request.strong_search_max_turns is not None:
            os.environ["STRONG_SEARCH_MAX_TURNS"] = str(request.strong_search_max_turns)
            updated["STRONG_SEARCH_MAX_TURNS"] = str(request.strong_search_max_turns)
            

        return {
            "status": "success",
            "message": "环境变量设置已更新",
            "updated": updated
        }
    except Exception as e:
        logger.error(f"更新环境变量设置时出错: {e}")
        raise HTTPException(status_code=500, detail=f"更新环境变量设置失败: {str(e)}")

@app.get("/settings/env")
async def get_env_settings():
    """获取当前强化搜索相关的环境变量设置"""
    try:
        settings = {
            "MODEL_NAME": os.environ.get("MODEL_NAME", ""),
            "MODEL_BASE_URL": os.environ.get("MODEL_BASE_URL", ""),
            "MODEL_API_KEY": "**********" if os.environ.get("MODEL_API_KEY") else "",  # 出于安全考虑不返回实际密钥
            "STRONG_SEARCH_MAX_TURNS": os.environ.get("STRONG_SEARCH_MAX_TURNS", ""),
        }
        
        return {
            "status": "success",
            "settings": settings
        }
    except Exception as e:
        logger.error(f"获取环境变量设置时出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取环境变量设置失败: {str(e)}")

# --- 运行服务器 (用于直接执行脚本) ---
if __name__ == "__main__":
    import socket
    import subprocess
    import sys
    
    # 检查端口是否被占用
    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0
            
    # 如果端口被占用，尝试终止进程
    if is_port_in_use(API_PORT):
        print(f"端口 {API_PORT} 已被占用，尝试终止相关进程...")
        try:
            if sys.platform.startswith('win'):
                subprocess.run(f"FOR /F \"tokens=5\" %P IN ('netstat -ano ^| find \"{API_PORT}\"') DO taskkill /F /PID %P", shell=True)
            else:
                subprocess.run(f"lsof -i :{API_PORT} -t | xargs kill -9", shell=True)
            print(f"端口 {API_PORT} 已释放")
        except Exception as e:
            print(f"无法释放端口: {e}")
            sys.exit(1)
    
    print(f"启动API服务器在端口 {API_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=API_PORT) 