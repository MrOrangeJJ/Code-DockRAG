#!/usr/bin/env python3
"""
强效代码搜索代理 - 基于Google ADK的智能代码库搜索工具
这个工具使用Google ADK进行代理操作，并通过事件系统跟踪执行过程
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Callable, Tuple, Union
from pathlib import Path
import sys
import time
import threading
import random
from datetime import datetime

# 导入Google ADK相关库 - 根据test_adk_qwen_events.py的实际导入方式
from google.adk import Agent, Runner
from google.adk.tools.function_tool import FunctionTool
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
import google.genai.types as types

# 导入项目自身的组件
from dotenv import load_dotenv
from .treesitter import (
    generate_project_structure,
    generate_formatted_structure
)
from .prompts import AGENT_INSTRUCTIONS
from .utils import get_codebase_path, load_config_file, load_lsp_cache, search_text

# 获取项目根目录（即code_dock的父目录）
root_dir = str(Path(os.path.dirname(os.path.abspath(__file__))).parent)
env_path = os.path.join(root_dir, '.env')
load_dotenv(env_path)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# 从环境变量获取最大轮次
MAX_TURNS = int(os.environ.get("STRONG_SEARCH_MAX_TURNS", "25"))  # 设置默认值

# 应用和会话ID前缀，用于Google ADK
APP_NAME = "code_dock_search"
USER_ID_PREFIX = "code_dock_user"
SESSION_ID_PREFIX = "code_dock_session"

class StrongSearchAgent:
    """
    强效代码搜索代理类，封装所有状态和功能
    使用面向对象方式实现，确保每个实例有自己独立的状态
    基于Google ADK实现
    """
    def __init__(self, codebase_name: str):
        """
        初始化代码搜索代理
        
        Args:
            codebase_name: 代码库名称
        """
        self.codebase_name = codebase_name
        paths = get_codebase_path(codebase_name)
        self.project_root = paths["code"]  # 代码库根目录
        self.project_structure = {}  # 项目结构
        self.relevant_files = set()  # 相关文件集合
        self.file_read_history = {}  # 文件读取历史
        self.adk_agent = None  # Google ADK Agent
        self.adk_runner = None  # Google ADK Runner
        self.session_service = None  # ADK会话服务

        self.analyzer_ready = load_config_file(codebase_name, "analyzer_ready")

        # 初始化项目结构
        try:
            self.project_structure = generate_formatted_structure(codebase_name)
        except Exception as e:
            logger.warning(f"初始化项目结构时出错: {e}, 将在需要时重新加载")
            
    async def get_file_content(self, file_path: str) -> Dict[str, Any]:
        """
        获取指定文件的内容
        
        Args:
            file_path: 文件路径
            
        Returns:
            包含文件内容的字典
        """
        # 构建完整路径
        if not os.path.isabs(file_path):
            full_path = os.path.join(self.project_root, file_path)
        else:
            full_path = file_path
        
        if not os.path.exists(full_path):
            # 文件不存在，尝试按文件名匹配
            filename = os.path.basename(file_path)
            if not filename:
                return {
                    "file_path": file_path,
                    "content": "",
                    "message": f"Invalid file path: {file_path}, please provide the correct file path",
                    "note": "Please call get_project_structure to better understand the project structure"
                }
            
            # 在整个项目中搜索文件名匹配的文件
            matched_files = []
            for root, dirs, files in os.walk(self.project_root):
                for file in files:
                    if file == filename:
                        rel_path = os.path.relpath(os.path.join(root, file), self.project_root)
                        matched_files.append(rel_path)
            
            # 根据匹配数量处理
            if len(matched_files) == 1:
                # 只找到一个匹配，返回其内容但提醒路径错误
                correct_path = matched_files[0]
                try:
                    with open(os.path.join(self.project_root, correct_path), 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                        self.file_read_history[correct_path] = content
                        return {
                            "file_path": correct_path,
                            "content": content,
                            "message": f"⚠️ Warning: The path '{file_path}' you provided is incorrect, but I found a file with the same name. The correct path is '{correct_path}'. Please use the correct path in subsequent queries.",
                            "note": "Please remember to use mark_file_relevance to mark whether this file is relevant to the question, using the correct path"
                        }
                except Exception as e:
                    logger.error(f"Error reading matched file: {correct_path} - {e}")
            elif len(matched_files) > 1:
                # 找到多个匹配，不返回内容，提醒确认
                paths_list = "\n".join([f"- {path}" for path in matched_files])
                return {
                    "file_path": file_path,
                    "content": "",
                    "message": f"⚠️ Warning: The path '{file_path}' you provided is incorrect, but I found {len(matched_files)} files with the same name. Please confirm which one you're looking for:\n{paths_list}",
                    "note": "Please call get_project_structure to understand the project structure better, and then use the correct complete path to query again"
                }
                
            # 如果没有匹配，返回原始错误
            return {
                "file_path": file_path,
                "content": "",
                "message": f"File does not exist: {file_path}, please ensure your file_path is correct (don't hastily conclude that the file truly doesn't exist, please recheck the project file paths)",
                "note": "Please call get_project_structure to understand the project structure better, ensuring you use the correct relative path"
            }
        
        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                self.file_read_history[file_path] = content
                return {
                    "file_path": file_path,
                    "content": content,
                    "message": "Successfully read file content",
                    "note": "Please remember to use mark_file_relevance to mark whether this file is relevant to the question"
                }
        except Exception as e:
            logger.error(f"Error reading file: {full_path} - {e}")
            return {
                "file_path": file_path,
                "content": "",
                "message": f"Error reading file: {str(e)}",
                "note": "Please remember to use mark_file_relevance to mark whether this file is relevant to the question"
            }

    def mark_file_relevance(self, file_path: str, is_relevant: bool) -> Dict[str, Any]:
        """
        标记文件是否与用户问题相关
        
        Args:
            file_path: 文件路径
            is_relevant: 是否相关
            
        Returns:
            操作结果
        """
        if is_relevant:
            self.relevant_files.add(file_path)
            message = f"File {file_path} has been marked as relevant"
        else:
            # 如果文件在相关文件集合中，则移除
            if file_path in self.relevant_files:
                self.relevant_files.remove(file_path)
                message = f"File {file_path} has been marked as not relevant"
            else:
                message = f"File {file_path} is already marked as not relevant"
        
        return {
            "file_path": file_path,
            "is_relevant": is_relevant,
            "message": message
        }

    def get_project_structure(self, random_string: str = "") -> Dict[str, Any]:
        """
        获取当前项目的结构信息，包括文件和目录的树状图
        
        Args:
            random_string: 无用参数，只是为了满足工具调用要求
            
        Returns:
            项目结构信息（同时包含原始结构和文本表示）
        """
        logger.info("Tool: Getting project structure... " + self.codebase_name)
        try:
            # 如果项目结构为空，则重新加载
            if not self.project_structure:
                self.project_structure = generate_formatted_structure(self.codebase_name)
            
            return {
                "structure": self.project_structure,
                "message": "Current project structure information"
            }
        except Exception as e:
            return {
                "structure": {},
                "message": f"Failed to get project structure: {str(e)}"
            }

    def find_references(self, file_path: str, symbol_name: str) -> Dict[str, Any]:
        """
        查找指定符号的引用
        
        Args:
            file_path: 符号所在文件路径
            symbol_name: 符号名称
            
        Returns:
            dict: 包含状态、消息和结果的字典
        """
        formatted_refs = {"status": "success", "message": "", "file_path": file_path, "result": []}
        cache = load_lsp_cache(self.codebase_name)

        rel_path = os.path.relpath(file_path, self.project_root) if os.path.isabs(file_path) else file_path
        full_path = os.path.join(self.project_root, rel_path)
        if not os.path.exists(full_path):
            filename = os.path.basename(file_path)
            if not filename:
                formatted_refs["status"] = "failed"
                formatted_refs["message"] = f"Invalid file path: {file_path}, please provide the correct file path. Please call get_project_structure to better understand the project structure"
                return formatted_refs

                
        if rel_path not in cache.keys():
            formatted_refs["status"] = "failed"
            formatted_refs["message"] = "File provided not found, please check the file path and call get_project_structure to re-analyze the project structure"
            return formatted_refs
        
        file_symbols = cache[rel_path]
         
        # 1. 尝试直接精确匹配
        if symbol_name in file_symbols:
            formatted_refs["result"] = file_symbols[symbol_name]
            return formatted_refs
        else:
            # 2. 尝试查找部分匹配 - 符号末尾匹配
            exact_suffix_matches = [s for s in file_symbols.keys() if s.endswith(f".{symbol_name}") or s == symbol_name]
            if len(exact_suffix_matches) == 1:
                formatted_refs["result"] = file_symbols[exact_suffix_matches[0]]
                return formatted_refs
            elif len(exact_suffix_matches) > 1:
                # 多个末尾匹配，列出所有可能
                formatted_refs["status"] = "warning"
                formatted_refs["message"] = f"Found multiple symbols matching '{symbol_name}':\n"
                for m in exact_suffix_matches:
                    formatted_refs["message"] += f"- {m}\n"
                formatted_refs["message"] += "Please choose a more specific name"
                return formatted_refs
            else:
                # 3. 如果没有精确后缀匹配，尝试包含匹配 symbol_name in symbol
                contains_matches = []
                for s in file_symbols.keys():
                    # 移除参数部分（如有），只比较方法名
                    base_name = symbol_name.split('(')[0] if '(' in symbol_name else symbol_name
                    s_base = s.split('(')[0] if '(' in s else s
                    
                    if base_name in s_base:
                        contains_matches.append(s)
                
                if len(contains_matches) == 1:
                    formatted_refs["result"] = file_symbols[contains_matches[0]]
                    return formatted_refs
                elif len(contains_matches) > 1:
                    # 多个包含匹配，列出所有可能
                    formatted_refs["status"] = "warning"
                    formatted_refs["message"] = f"Found multiple symbols containing '{symbol_name}':\n"
                    for i, m in enumerate(contains_matches):
                        formatted_refs["message"] += f"{i+1}. {m}\n"
                    formatted_refs["message"] += "Please choose a more specific name"
                    return formatted_refs
        
        formatted_refs["status"] = "failed"
        formatted_refs["message"] = f"No symbols matching '{symbol_name}' were found"
        return formatted_refs

    def _create_adk_tools(self) -> List[FunctionTool]:
        """创建Google ADK的工具函数列表"""

        # 定义获取文件内容的工具
        async def get_file_content_tool(file_path: str) -> Dict[str, Any]:
            """Retrieves the complete content of a specific file from the codebase.

            If the provided file_path doesn't exist, the tool will attempt to find files with the same name.
            If a unique match is found, it will return its content while noting the path error.
            If multiple matches are found, it will ask for a more precise path.

            Args:
                file_path: The relative path to the file from the project root directory.

            Returns:
                A dictionary containing the file path, content, and status messages.
            """
            # 将异步函数转为同步调用
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环已经在运行，使用线程运行
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = asyncio.run_coroutine_threadsafe(self.get_file_content(file_path), loop)
                    return future.result()
            else:
                # 否则直接运行异步函数
                return loop.run_until_complete(self.get_file_content(file_path))

        # 定义标记文件相关性的工具
        def mark_file_relevance_tool(file_path: str, is_relevant: bool) -> Dict[str, Any]:
            """Marks whether a file is relevant to the current user query.

            The list of relevant files will be used in the context for the final answer.

            Args:
                file_path: The relative path of the file to mark.
                is_relevant: Boolean indicating whether the file is relevant (True) or not (False).

            Returns:
                A dictionary containing the operation status.
            """
            return self.mark_file_relevance(file_path, is_relevant)
            
        # 定义获取项目结构的工具
        def get_project_structure_tool(random_string: str = "") -> Dict[str, Any]:
            """Retrieves an overview of the current codebase structure.

            Returns a formatted text representation of the hierarchical structure, including files and directories,
            to help understand the code organization.

            Args:
                random_string: Not used, just to satisfy the interface.

            Returns:
                A dictionary containing the formatted structure text and status message.
            """
            return self.get_project_structure(random_string)
            
        # 定义查找代码引用的工具
        def find_code_references_tool(symbol_name: str, file_path: str) -> Dict[str, Any]:
            """Finds all references to a specified symbol (function or class) throughout the codebase.

            Similar to the 'Go to References' functionality in IDEs.

            Args:
                symbol_name: The name of the function or class to find references for.
                file_path: The relative path to the file containing the function or class definition.

            Returns:
                A dictionary containing a list of references or error message.
            """
            return self.find_references(file_path, symbol_name)
        
        # 定义搜索文本的工具
        def search_text_tool(keyword: str) -> Dict[str, Any]:
            """Searches for files in the codebase containing the specified keyword.

            Args:
                keyword: The keyword to search for.

            Returns:
                A dictionary containing the search results.
            """
            return search_text(self.codebase_name, keyword)

        # 创建 FunctionTool 实例列表
        tools = [
            FunctionTool(func=get_file_content_tool),
            FunctionTool(func=mark_file_relevance_tool),
            FunctionTool(func=get_project_structure_tool),
            FunctionTool(func=search_text_tool)
        ]
        
        if self.analyzer_ready:
            tools.append(FunctionTool(func=find_code_references_tool))
            
        return tools

    def _initialize_adk_components(self, query: str):
        """初始化Google ADK组件（Agent、Runner等）"""
        # 获取当前环境变量中的模型设置
        model_name = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")
        model_base_url = os.environ.get("MODEL_BASE_URL", "")
        model_api_key = os.environ.get("MODEL_API_KEY", "")
        
        # 创建模型 - 根据test_adk_qwen_events.py中的正确用法
        model = LiteLlm(
            model=f"openai/{model_name}",  # 添加openai/前缀
            api_base=model_base_url,
            api_key=model_api_key,
        )
        
        # 创建ADK Agent
        self.adk_agent = Agent(
            model=model,
            name="Code_Search_Expert",
            instruction=AGENT_INSTRUCTIONS.format(query=query),
            tools=self._create_adk_tools()
        )
        
        # 创建会话服务
        self.session_service = InMemorySessionService()
        
        # 创建Runner
        self.adk_runner = Runner(
            app_name=APP_NAME,
            agent=self.adk_agent,
            session_service=self.session_service
        )
        
        # 生成用户ID和会话ID
        self.user_id = f"{USER_ID_PREFIX}_{int(time.time())}"
        self.session_id = f"{SESSION_ID_PREFIX}_{int(time.time())}"
        
        # 创建会话
        self.session_service.create_session(
            user_id=self.user_id,
            session_id=self.session_id,
            app_name=APP_NAME
        )

    async def run_search(self, query: str, trace_id: str = None, tracing_disabled: bool = False) -> Dict[str, Any]:
        """
        运行代码搜索，核心执行函数
        
        Args:
            query: 用户查询
            trace_id: 可选的追踪ID，用于关联处理器
            tracing_disabled: 是否禁用追踪，如果为None则使用全局设置
            
        Returns:
            Dict[str, Any]: 包含搜索结果的字典
        """
            # 动态获取最大轮次，如果环境变量已更新则使用新值
        max_turns = int(os.environ.get("STRONG_SEARCH_MAX_TURNS", str(MAX_TURNS)))
            
        # 初始化Google ADK组件
        try:
            self._initialize_adk_components(query)
            
            # 发送通知：已初始化
            if trace_id:
                global_ws_processor.send_log(
                    trace_id=trace_id,
                    message="已初始化代理和会话服务",
                    level="info"
                )
                global_ws_processor.send_progress(
                    trace_id=trace_id,
                    progress=0.1,
                    status="初始化完成"
                )
        except Exception as init_e:
            logger.error(f"初始化ADK组件失败: {init_e}", exc_info=True)
            if trace_id:
                global_ws_processor.send_log(
                    trace_id=trace_id,
                    message=f"初始化失败: {init_e}",
                    level="error"
                )
            return {
                "answer": f"初始化失败: {init_e}",
                   "relevant_files": [], 
                "execution_time": 0
            }
        
        # 记录开始时间
        start_time = time.time()
        logger.info(f"开始执行ADK代理...")
        
        # 构建输入消息
        user_message = types.Content(
            parts=[types.Part(text=f"I need to answer a question about this project: \"{query}\". Please start by analyzing the project structure.")],
            role="user"
        )
        
        try:
            # 发送开始执行消息
            if trace_id:
                global_ws_processor.send_log(
                    trace_id=trace_id,
                    message="开始运行代理，请等待...",
                    level="info"
                )
                global_ws_processor.send_progress(
                    trace_id=trace_id,
                    progress=0.2,
                    status="代理开始执行"
                )
            
            # 创建事件处理对象
            event_handler = ADKEventHandler(
                agent=self,
                trace_id=trace_id,
                query=query
            )
            
            # 运行代理并处理事件
            final_answer = await event_handler.run_agent_with_events(
                runner=self.adk_runner,
                user_id=self.user_id,
                session_id=self.session_id,
                message=user_message,
                max_turns=max_turns
            )
            
            # 计算执行时间
            execution_time = time.time() - start_time
            
            # 构建结果
            result = {
                "answer": final_answer,
                "project_structure": self.project_structure,
                "relevant_files": sorted(list(self.relevant_files)),
                "execution_time": execution_time,
                "file_read_history": self.file_read_history
            }
            
            # 发送完成通知
            if trace_id:
                global_ws_processor.send_log(
                    trace_id=trace_id,
                    message=f"执行完成，耗时 {execution_time:.2f} 秒",
                    level="success"
                )
                global_ws_processor.send_progress(
                    trace_id=trace_id,
                    progress=1.0,
                    status="搜索完成"
                )
                global_ws_processor.send_result(
                    trace_id=trace_id,
                    result=result
                )
            
            return result
            
        except Exception as run_e:
            logger.error(f"运行ADK代理失败: {run_e}", exc_info=True)
            execution_time = time.time() - start_time
            
            if trace_id:
                global_ws_processor.send_log(
                    trace_id=trace_id,
                    message=f"执行失败: {run_e}",
                    level="error"
                )
                global_ws_processor.send_progress(
                    trace_id=trace_id,
                    progress=1.0,
                    status="搜索失败"
                )
            
            return {
                "answer": f"执行失败: {run_e}",
                "relevant_files": sorted(list(self.relevant_files)) if self.relevant_files else [],
                "execution_time": execution_time
            }


class ADKEventHandler:
    """事件处理器，处理Agent执行过程中的事件并转换为WebSocket消息"""
    
    def __init__(self, agent: StrongSearchAgent, trace_id: Optional[str], query: str):
        """
        初始化事件处理器
        
        Args:
            agent: StrongSearchAgent实例
            trace_id: 可选的追踪ID
            query: 用户查询
        """
        self.agent = agent
        self.trace_id = trace_id
        self.query = query
        self.final_answer = ""
        self.current_turn = 0
        self.max_turns = int(os.environ.get("STRONG_SEARCH_MAX_TURNS", "25"))
        
    async def run_agent_with_events(self, runner, user_id, session_id, message, max_turns):
        """
        运行代理并处理事件
        
        Args:
            runner: ADK Runner实例
            user_id: 用户ID
            session_id: 会话ID
            message: 输入消息
            max_turns: 最大轮次
            
        Returns:
            str: 最终答案
        """
        self.max_turns = max_turns
        
        # 发送开始消息
        if self.trace_id:
            global_ws_processor.on_trace_start(self.trace_id, self.query)
            
        # 获取事件流
        events = runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message
        )
        
        try:
            # 处理事件流中的每个事件
            async for event in events:

                self._process_event(event)
                
                # # 检查是否超过最大轮次
                # self.current_turn += 1
                # if self.current_turn >= self.max_turns:
                #     logger.warning(f"已达到最大轮次 {self.max_turns}，强制结束")
                #     if self.trace_id:
                #         global_ws_processor.send_log(
                #             trace_id=self.trace_id,
                #             message=f"已达到最大轮次 {self.max_turns}，强制结束",
                #             level="warning"
                #         )
                #     break
        except Exception as e:
            logger.error(f"处理事件流时出错: {e}", exc_info=True)
            if self.trace_id:
                global_ws_processor.send_log(
                    trace_id=self.trace_id,
                    message=f"处理事件流时出错: {e}",
                    level="error"
                )
        finally:
            # 发送结束消息
            if self.trace_id:
                global_ws_processor.on_trace_end(self.trace_id, self.final_answer)
                
        return self.final_answer
                
    async def _process_event(self, event):
        """
        处理单个事件，使用与test_adk_qwen_events.py相同的模式
        
        Args:
            event: ADK事件
        """
        # 获取事件类型和来源 - 与test_adk_qwen_events.py一致
        author = getattr(event, 'author', '未知来源')
        is_final = (hasattr(event, 'is_final_response') and 
                    callable(event.is_final_response) and 
                    event.is_final_response())
                    
        # 处理思考和生成过程
        if hasattr(event, 'content') and event.content and hasattr(event.content, 'parts'):
            for part in event.content.parts:
                if hasattr(part, 'text') and part.text:
                    # 获取文本内容
                    text_content = part.text
                    
                    # 根据事件是最终响应还是中间思考过程决定处理方式
                    if is_final:
                        # 这是最终回答
                        self.final_answer = text_content
                        logger.info(f"收到最终答案: {text_content[:100]}...")
                    elif getattr(event, 'partial', False):
                        # 这是中间思考过程
                        if self.trace_id:
                            global_ws_processor.send_log(
                                trace_id=self.trace_id,
                                message=text_content,
                                level="agent_thinking"
                            )
                            # 更新进度
                            progress = min(0.3 + (self.current_turn / self.max_turns * 0.6), 0.9)
                            global_ws_processor.send_progress(
                                trace_id=self.trace_id,
                                progress=progress,
                                status="代理思考中..."
                            )
        else:
            # 其他输出内容
            if self.trace_id:
                global_ws_processor.send_log(
                    trace_id=self.trace_id,
                    message=text_content,
                    level="info"
                )
        
        # 处理工具调用 - 使用test_adk_qwen_events.py中相同的方法
        function_calls = event.get_function_calls() if hasattr(event, 'get_function_calls') and callable(event.get_function_calls) else []
        if function_calls:
            for call in function_calls:
                # 获取工具名称和参数
                tool_name = call.name
                tool_args = call.args
                
                # 发送工具调用消息
                if self.trace_id:
                    tool_call_data = {
                        "tool_name": tool_name,
                        "parameters": tool_args,
                        "timestamp": time.time()
                    }
                    global_ws_processor.send_log(
                        trace_id=self.trace_id,
                        message=tool_call_data,
                        level="tool_call"
                    )
        
        # 处理工具响应 - 使用test_adk_qwen_events.py中相同的方法
        function_responses = event.get_function_responses() if hasattr(event, 'get_function_responses') and callable(event.get_function_responses) else []
        if function_responses:
            for resp in function_responses:
                # 获取工具名称和结果
                tool_name = resp.name
                tool_response = resp.response
                
                # 发送工具输出消息
                if self.trace_id:
                    tool_output_data = {
                        "tool_name": tool_name,
                        "output_preview": json.dumps(tool_response, ensure_ascii=False),
                        "is_output": True,
                        "timestamp": time.time()
                    }
                    global_ws_processor.send_log(
                        trace_id=self.trace_id,
                        message=tool_output_data,
                        level="tool_output"
                    )


# 兼容性函数 - 保持原有API的向后兼容性
async def run_agent(codebase_name: str, query: str, trace_id: str = None, tracing_disabled: bool = None) -> Dict[str, Any]:
    """
    运行代码搜索代理。兼容旧的API调用方式。
    
    Args:
        codebase_name: 代码库名称
        query: 用户查询
        trace_id: 可选的追踪ID，用于关联处理器
        tracing_disabled: 是否禁用追踪，如果为None则使用全局设置
        
    Returns:
        代理的最终输出和相关文件
    """
    # 创建代理实例
    agent = StrongSearchAgent(codebase_name)
    
    # 运行搜索
    result = await agent.run_search(query, trace_id=trace_id, tracing_disabled=tracing_disabled)
    
    # 从结果中移除文件读取历史，保持返回格式兼容
    if "file_read_history" in result:
        del result["file_read_history"]
    
    return result
    

# ---------------- 全局WebSocket事件处理器 ----------------
class GlobalWebSocketProcessor:
    """全局WebSocket事件处理器，接收和发送WebSocket消息"""
    def __init__(self):
        self.routes = {}  # {trace_id: (client_id, manager, timestamp)}
        self.lock = threading.Lock()
        self.cleanup_threshold = 3600  # 1小时未活动的路由将被清理
        logger.info("[GlobalWebSocketProcessor] 初始化")
    
    def register(self, trace_id: str, client_id: str, manager: Any):
        """注册一个新的trace_id到特定客户端"""
        with self.lock:
            self.routes[trace_id] = (client_id, manager, time.time())
        logger.info(f"[GlobalWebSocketProcessor] 注册trace_id: {trace_id} -> client_id: {client_id}")
    
    def unregister(self, trace_id: str):
        """注销一个trace_id"""
        with self.lock:
            if trace_id in self.routes:
                del self.routes[trace_id]
                logger.info(f"[GlobalWebSocketProcessor] 注销trace_id: {trace_id}")
    
    def _get_client_manager(self, trace_id: str) -> Tuple[str, Any, float]:
        """获取对应trace的客户端ID和管理器"""
        with self.lock:
            return self.routes.get(trace_id, (None, None, 0))
    
    def cleanup_expired_routes(self):
        """清理过期的路由"""
        now = time.time()
        expired_routes = []
        
        with self.lock:
            for trace_id, (client_id, _, timestamp) in self.routes.items():
                if now - timestamp > self.cleanup_threshold:
                    expired_routes.append(trace_id)
            
            for trace_id in expired_routes:
                del self.routes[trace_id]
                logger.info(f"[GlobalWebSocketProcessor] 清理过期路由: {trace_id}")
    
    def send_log(self, trace_id: str, message: Any, level: str = "info"):
        """发送日志消息"""
        client_id, manager, _ = self._get_client_manager(trace_id)
        if client_id and manager:
            asyncio.create_task(manager.send_log(client_id, message, level))
    
    def send_progress(self, trace_id: str, progress: float, status: str = ""):
        """发送进度信息"""
        client_id, manager, _ = self._get_client_manager(trace_id)
        if client_id and manager:
            asyncio.create_task(manager.send_progress(client_id, progress, status))
    
    def send_result(self, trace_id: str, result: Dict[str, Any]):
        """发送最终结果"""
        client_id, manager, _ = self._get_client_manager(trace_id)
        if client_id and manager:
            asyncio.create_task(manager.send_result(client_id, result))
    
    def send_error(self, trace_id: str, error: str):
        """发送错误信息"""
        client_id, manager, _ = self._get_client_manager(trace_id)
        if client_id and manager:
            asyncio.create_task(manager.send_error(client_id, error))
            
    def on_trace_start(self, trace_id: str, query: str):
        """追踪开始事件"""
        client_id, manager, _ = self._get_client_manager(trace_id)
        if client_id and manager:
            self.send_log(
                trace_id=trace_id,
                message=f"开始搜索: {query}",
                level="info"
            )
            
    def on_trace_end(self, trace_id: str, final_answer: str):
        """追踪结束事件"""
        client_id, manager, _ = self._get_client_manager(trace_id)
        if client_id and manager:
            self.send_log(
                trace_id=trace_id,
                message="搜索完成，最终结果已就绪",
                level="success"
            )


# 创建全局WebSocket处理器实例
global_ws_processor = GlobalWebSocketProcessor()


# ---------------- 全局文件日志处理器 ----------------
class GlobalFileProcessor:
    """全局文件日志处理器，记录执行日志到文件"""
    def __init__(self):
        self.routes = {}  # {trace_id: (log_handler, timestamp)}
        self.lock = threading.Lock()
        self.cleanup_threshold = 3600  # 1小时未活动的路由将被清理
    
    def register(self, trace_id: str, log_handler: logging.FileHandler):
        """注册一个新的trace_id到日志处理器"""
        with self.lock:
            self.routes[trace_id] = (log_handler, time.time())
    
    def unregister(self, trace_id: str):
        """注销一个trace_id"""
        with self.lock:
            if trace_id in self.routes:
                handler, _ = self.routes[trace_id]
                handler.close()
                del self.routes[trace_id]
    
    def _get_log_handler(self, trace_id: str) -> Tuple[logging.FileHandler, float]:
        """获取对应trace的日志处理器"""
        with self.lock:
            return self.routes.get(trace_id, (None, 0))
    
    def cleanup_expired_routes(self):
        """清理过期的路由"""
        now = time.time()
        expired_routes = []
        
        with self.lock:
            for trace_id, (_, timestamp) in self.routes.items():
                if now - timestamp > self.cleanup_threshold:
                    expired_routes.append(trace_id)
            
            for trace_id in expired_routes:
                handler, _ = self.routes[trace_id]
                handler.close()
                del self.routes[trace_id]
                
    def log_message(self, trace_id: str, message: str, level: int = logging.INFO):
        """记录日志消息到文件"""
        handler, _ = self._get_log_handler(trace_id)
        if handler:
            logger = logging.getLogger(f"trace.{trace_id}")
            logger.setLevel(logging.DEBUG)
            logger.addHandler(handler)
            logger.log(level, message)
            logger.removeHandler(handler)


# 创建全局文件日志处理器实例
global_file_processor = GlobalFileProcessor()
global_ws_processor = GlobalWebSocketProcessor()

def set_trace_processors(*args, **kwargs):
    pass

def set_tracing_disabled(*args, **kwargs):
    pass


if __name__ == "__main__":
    pass