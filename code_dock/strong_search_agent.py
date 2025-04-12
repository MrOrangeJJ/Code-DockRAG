#!/usr/bin/env python3
"""
强效代码搜索代理 - 基于LLM的智能代码库搜索工具
这个工具更加智能，可以不断探索直到找到满意答案
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Callable, Tuple
from openai import (
    AsyncOpenAI, 
    APITimeoutError, 
    APIConnectionError, 
    RateLimitError, 
    InternalServerError
)
import httpx # 导入 httpx
from tenacity import ( # 导入 tenacity 相关模块
    retry, 
    stop_after_attempt,
    retry_if_result,
)

from pathlib import Path
import argparse
import sys
import time
from .treesitter import (
    generate_project_structure,
    generate_formatted_structure
)
from datetime import datetime # 确保导入 datetime
from dotenv import load_dotenv
from .prompts import AGENT_INSTRUCTIONS
from .utils import get_codebase_path, load_config_file, load_lsp_cache, search_text
from agents import (
    Agent, Runner, OpenAIChatCompletionsModel, function_tool,
    Trace, Span, TracingProcessor, set_trace_processors, set_tracing_disabled,
    RunConfig,
)
import threading
import random

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

class StrongSearchAgent:
    """
    强效代码搜索代理类，封装所有状态和功能
    使用面向对象方式实现，确保每个实例有自己独立的状态
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
        self.openai_client = None  # OpenAI客户端

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
                    "note": "Please call wrapped_get_project_structure to better understand the project structure"
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
                            "note": "Please remember to use wrapped_mark_file_relevance to mark whether this file is relevant to the question, using the correct path"
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
                    "note": "Please call wrapped_get_project_structure to understand the project structure better, and then use the correct complete path to query again"
                }
                
            # 如果没有匹配，返回原始错误
            return {
                "file_path": file_path,
                "content": "",
                "message": f"File does not exist: {file_path}, please ensure your file_path is correct (don't hastily conclude that the file truly doesn't exist, please recheck the project file paths)",
                "note": "Please call wrapped_get_project_structure to understand the project structure better, ensuring you use the correct relative path"
            }
        
        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                self.file_read_history[file_path] = content
                return {
                    "file_path": file_path,
                    "content": content,
                    "message": "Successfully read file content",
                    "note": "Please remember to use wrapped_mark_file_relevance to mark whether this file is relevant to the question"
                }
        except Exception as e:
            logger.error(f"Error reading file: {full_path} - {e}")
            return {
                "file_path": file_path,
                "content": "",
                "message": f"Error reading file: {str(e)}",
                "note": "Please remember to use wrapped_mark_file_relevance to mark whether this file is relevant to the question"
            }

    async def mark_file_relevance(self, file_path: str, is_relevant: bool) -> Dict[str, Any]:
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

    async def get_project_structure(self, random_string: str = "") -> Dict[str, Any]:
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

    def _create_tool_functions(self) -> List[Callable]:
        """创建工具函数列表，将实例方法包装为function_tool"""

        # --- 工具定义 ---

        @function_tool
        async def wrapped_get_file_content(file_path: str) -> Dict[str, Any]:
            """Retrieves the complete content of a specific file from the codebase.

            If the provided file_path doesn't exist, the tool will attempt to find files with the same name across the project.
            If a unique match is found, it will return its content while noting the path error.
            If multiple matches are found, it will ask for a more precise path.

            Args:
                file_path: The relative path to the file from the project root directory.

            Returns:
                A dictionary containing the file path, content, and status messages.
            """
            return await self.get_file_content(file_path)
            
        @function_tool
        async def wrapped_mark_file_relevance(file_path: str, is_relevant: bool) -> Dict[str, Any]:
            """Marks whether a file is relevant to the current user query.

            The list of relevant files will be used in the context for the final answer.

            Args:
                file_path: The relative path of the file to mark.
                is_relevant: Boolean indicating whether the file is relevant (True) or not (False).

            Returns:
                A dictionary containing the operation status.
            """
            return await self.mark_file_relevance(file_path, is_relevant)
            
        @function_tool
        async def wrapped_get_project_structure(random_string: str = "") -> Dict[str, Any]:
            """Retrieves an overview of the current codebase structure.

            Returns a formatted text representation of the hierarchical structure, including files, classes, and methods,
            to help understand the code organization.
            Note: This tool doesn't accept actual parameters; random_string is only used to satisfy the interface.

            Returns:
                A dictionary containing the formatted structure text and status message.
            """
            # 注意：这里的 random_string 参数是为了兼容性，实际未使用
            return await self.get_project_structure(random_string)
            
        @function_tool
        async def wrapped_find_code_references(symbol_name: str, file_path: Optional[str] = None) -> Dict[str, Any]:
            """Finds all references to a specified symbol (function or class) throughout the codebase.

            Similar to the 'Go to References' functionality in IDEs. Can search within a specific file or across the entire project.

            Args:
                symbol_name: The name of the function or class to find references for.
                file_path: The relative path to the file containing the function or class definition. (Required)

            Returns:
                A dictionary containing a list of references or error message. References include file paths and line numbers where the symbol is referenced.
            """
            return await self.find_references(file_path, symbol_name)
        
        @function_tool
        async def wrapped_search_text(keyword: str) -> Dict[str, Any]:
            """Searches for files in the codebase containing the specified keyword.

            Args:
                keyword: The keyword to search for.

            Returns:
                A dictionary containing the search results.
            """
            return search_text(self.codebase_name, keyword)

        # --- 工具列表 ---
        tools_list = [
            wrapped_get_file_content, 
            wrapped_mark_file_relevance, 
            wrapped_get_project_structure,
            wrapped_search_text
        ]
        
        if self.analyzer_ready:
            tools_list.append(wrapped_find_code_references)
            
        return tools_list

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
        # 准备工具函数
        tool_functions = self._create_tool_functions()
        
        # 每次运行时获取当前的环境变量，而不是使用os.getenv，确保使用最新值
        model_base_url = os.environ.get("MODEL_BASE_URL", "")
        model_api_key = os.environ.get("MODEL_API_KEY", "")
        
        
        # 创建客户端时传入自定义的 http_client
        self.openai_client = AsyncOpenAI(
            base_url=model_base_url,
            api_key=model_api_key,
            http_client=CustomRetryClient() # 使用自定义客户端
            # 注意: AsyncOpenAI 自身的 max_retries 在使用自定义 http_client 时可能不再生效或行为改变
        )
        
        # 创建代理 
        try:
            # 获取当前环境变量中的模型名称
            model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")
            
            # 动态获取最大轮次，如果环境变量已更新则使用新值
            max_turns = int(os.environ.get("STRONG_SEARCH_MAX_TURNS", str(MAX_TURNS)))
            
            
            agent = Agent(
                name="Code Search Expert",
                instructions=AGENT_INSTRUCTIONS.format(query=query),
                tools=tool_functions,
                model=OpenAIChatCompletionsModel(
                    model=model,
                    openai_client=self.openai_client,
                )
            )
        except Exception as agent_init_e:
            logger.error(f"Failed to create Agent: {agent_init_e}", exc_info=True)
            return {"answer": f"Internal error: Unable to initialize search agent", 
                   "relevant_files": [], 
                   "execution_time": 0}
        
        # 准备初始消息
        messages = [
            {"role": "system", "content": "You are a code search expert who can answer user questions about codebases by exploring project structure and code content."},
            {"role": "user", "content": f"I need to answer a question about this project: \"{query}\". Please start by analyzing the project structure."}
        ]
        
        logger.info(f"Running Agent Runner (Max Turns: {max_turns})...")
        result_data = {}
        start_time = time.time()
        try:
            # 创建RunConfig配置
            run_config = RunConfig(
                trace_id=trace_id,  # 使用传入的trace_id
                tracing_disabled=tracing_disabled,
                workflow_name=f"Code Search - {self.codebase_name}",
                trace_metadata={"codebase": self.codebase_name, "query": query}
            )
            
            # 使用RunConfig，并且使用动态获取的最大轮次
            result = await Runner.run(
                agent, 
                input=messages, 
                max_turns=max_turns,  # 使用当前环境变量中的设置
                run_config=run_config
            )
            final_answer = getattr(result, 'final_output', "Failed to get final output")
            
        except Exception as agent_run_error:
            logger.error(f"Agent Runner.run execution error: {agent_run_error}", exc_info=True)
            final_answer = f"Agent execution failed: {agent_run_error}"
        finally:
            execution_time = time.time() - start_time
            result_data = {
                "answer": final_answer,
                "project_structure": self.project_structure,  # 添加项目结构到结果中
                "relevant_files": sorted(list(self.relevant_files)),  # 确保顺序一致
                "execution_time": execution_time,
                "file_read_history": self.file_read_history,  # 添加文件读取历史
                "trace_id": trace_id  # 返回trace_id，方便客户端关联
            }
            
        logger.info(f"Agent Runner completed, time taken: {execution_time:.2f}s")
        return result_data
    
    async def find_references(self, file_path, symbol_name):
        """
        异步查找指定符号的引用
        
        Args:
            file_path: 符号所在文件路径
            symbol_name: 符号名称
            symbol_type: 符号类型（可选）
            
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
                formatted_refs["message"] = f"Invalid file path: {file_path}, please provide the correct file path. Please call wrapped_get_project_structure to better understand the project structure"
                return formatted_refs

                
        if rel_path not in cache.keys():
            formatted_refs["status"] = "failed"
            formatted_refs["message"] = "File provided not found, please check the file path and call wrapped_get_project_structure to re-analyze the project structure"
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
    

# ---------------- 全局WebSocket追踪处理器 ----------------
class GlobalWebSocketTracingProcessor(TracingProcessor):
    """全局WebSocket追踪处理器，内部路由到具体客户端"""
    def __init__(self):
        self.routes = {}  # {trace_id: (client_id, manager, timestamp)}
        self.lock = threading.Lock()
        self.cleanup_threshold = 3600  # 1小时未活动的路由将被清理
        logger.info("[GlobalWebSocketTracingProcessor] 初始化")
    
    def register(self, trace_id: str, client_id: str, manager: Any):
        """注册一个新的trace_id到特定客户端"""
        with self.lock:
            self.routes[trace_id] = (client_id, manager, time.time())
        logger.info(f"[GlobalWebSocketTracingProcessor] 注册trace_id: {trace_id} -> client_id: {client_id}")
    
    def unregister(self, trace_id: str):
        """注销一个trace_id"""
        with self.lock:
            if trace_id in self.routes:
                del self.routes[trace_id]
                logger.info(f"[GlobalWebSocketTracingProcessor] 注销trace_id: {trace_id}")
    
    def _get_client_manager(self, obj) -> Tuple[str, Any, float]:
        """获取对应trace的客户端ID和管理器"""
        trace_id = getattr(obj, 'trace_id', None)
        if not trace_id:
            return None, None, 0
            
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
                logger.info(f"[GlobalWebSocketTracingProcessor] 清理过期路由: {trace_id}")
    
    def _format_message(self, span: Span[Any], client_id: str) -> Optional[Dict[str, Any]]:
        """从Span格式化WebSocket消息"""
        try:
            # 辅助函数：从多个可能的来源提取工具名称
            def extract_tool_name(obj) -> str:
                tool_name = None
                # 直接从属性获取
                if not tool_name and hasattr(obj, 'function_name') and obj.function_name:
                    tool_name = obj.function_name
                if not tool_name and hasattr(obj, 'tool_name') and obj.tool_name:
                    tool_name = obj.tool_name
                if not tool_name and hasattr(obj, 'name') and obj.name:
                    tool_name = obj.name
                
                # 从字典数据中获取
                if not tool_name and isinstance(obj, dict):
                    if 'function_name' in obj and obj['function_name']:
                        tool_name = obj['function_name']
                    elif 'name' in obj and obj['name']:
                        tool_name = obj['name']
                    elif 'function' in obj and isinstance(obj['function'], dict):
                        if 'name' in obj['function'] and obj['function']['name']:
                            tool_name = obj['function']['name']
                
                # 从input中获取
                if not tool_name and hasattr(obj, 'input'):
                    input_data = obj.input
                    if isinstance(input_data, dict):
                        if 'function_name' in input_data and input_data['function_name']:
                            tool_name = input_data['function_name']
                        elif 'name' in input_data and input_data['name']:
                            tool_name = input_data['name']
                
                # 最后的fallback
                if not tool_name:
                    tool_name = "未知工具"
                
                return tool_name
                
            span_type_name = type(span.span_data).__name__
            span_data = span.span_data
            message = None
            level = "info" # 默认级别
            
            # 安全获取manager
            trace_id = getattr(span, 'trace_id', '')
            with self.lock:
                route_info = self.routes.get(trace_id)
                
            if not route_info:
                logger.warning(f"未找到trace_id为{trace_id}的路由信息")
                return None
                
            _, manager, _ = route_info

            if span_type_name == 'GenerationSpanData':
   
                output_content = "[无输出]"
                tool_call_decision = None
                if hasattr(span_data, 'output') and span_data.output:
                    try:
                        if isinstance(span_data.output, list) and len(span_data.output) > 0 and isinstance(span_data.output[0], dict):
                            assistant_message = span_data.output[0].get('content')
                            tool_calls = span_data.output[0].get('tool_calls')
                            if assistant_message:
                                output_content = f'{assistant_message[:150]}...'
                                # 检查是否包含推理内容，发送为agent_thinking类型
                                if "我来思考" in assistant_message or "我需要分析" in assistant_message or "让我思考" in assistant_message:
                                    asyncio.create_task(manager.send_log(
                                        client_id, 
                                        assistant_message, 
                                        level="agent_thinking"
                                    ))
                                    return None
                            elif tool_calls:
                                tool_details = []
                                for tc in tool_calls:
                                    # 使用公共提取函数
                                    name = extract_tool_name(tc)
                                    function_data = tc.get('function', {})
                                    tool_details.append({"tool_name": name, "parameters": function_data.get('arguments', {})})
                                output_content = f"决定调用工具: {', '.join([d['tool_name'] for d in tool_details])}"
                                tool_call_decision = tool_details # 保存决策详情
                        else:
                            output_content = f'{json.dumps(span_data.output, ensure_ascii=False, default=str)[:100]}...'
                    except Exception as e:
                        output_content = f"[无法解析输出: {str(e)}]"
                
                if tool_call_decision:
                     # 发送每个工具调用决策
                     for decision in tool_call_decision:
                         asyncio.create_task(manager.send_log(client_id, decision, level="tool_call_decision"))
                     # 不再发送合并的思考消息
                     return None 
                else:
                     message = f"🧠 Agent 思考/决策: {output_content}"
                     level = "info"
                     if hasattr(span_data, 'error') and span_data.error:
                         message += f" (错误: {span_data.error})"
                         level = "error"
                     
                     # 将思考/决策内容作为agent_thinking类型发送
                     if "思考" in output_content or "分析" in output_content or "查看" in output_content:
                        asyncio.create_task(manager.send_log(
                            client_id, 
                            output_content, 
                            level="agent_thinking"
                        ))
                        return None
                
            elif span_type_name == 'FunctionSpanData':

                # 使用公共提取函数获取工具名称
                tool_name = extract_tool_name(span_data)
                
                params = {}
                if hasattr(span_data, 'input'):
                    try: 
                        if isinstance(span_data.input, str):
                            params = json.loads(span_data.input)
                        elif isinstance(span_data.input, dict):
                            params = span_data.input
                        else:
                            params = {"raw_input": str(span_data.input)[:200]}
                    except Exception as e: 
                        params = {"raw_input": str(span_data.input)[:200]}
                
                # 确保params是JSON可序列化的
                try:
                    # 测试序列化
                    json.dumps(params, ensure_ascii=False, default=str)
                except Exception as e:
                    # 如果不可序列化，使用简化版本
                    params = {"raw_input": str(params)[:200]}
                    
                # 发送工具调用信息
                tool_call_message = {"tool_name": tool_name, "parameters": params, "timestamp": time.time()}
                asyncio.create_task(manager.send_log(client_id, tool_call_message, level="tool_call"))
                
                # 发送工具输出信息
                output_preview = "[无输出或无法解析]"
                output_level = "tool_output"
                if hasattr(span_data, 'error') and span_data.error:
                    output_preview = f"❌ 调用失败: {span_data.error}"
                    output_level = "error" # 将错误也视为一种输出
                elif hasattr(span_data, 'output'):
                    try: output_preview = f'{json.dumps(span_data.output, ensure_ascii=False, default=str)}'
                    except: pass # 保持默认
                
                tool_output_message = {"tool_name": tool_name, "output_preview": output_preview, "is_output": True, "timestamp": time.time()}
                asyncio.create_task(manager.send_log(client_id, tool_output_message, level=output_level))
                return None # 已分开发送调用和输出，不返回合并消息
            elif span_type_name == "Reasoning" or span_type_name == "ReasoningStep" or span_type_name == "AgentReasoning":
                # 专门处理推理/思考类型的Span
                thinking_content = ""
                if hasattr(span_data, 'thinking') and span_data.thinking:
                    thinking_content = span_data.thinking
                elif hasattr(span_data, 'reasoning') and span_data.reasoning:
                    thinking_content = span_data.reasoning
                elif hasattr(span_data, 'content') and span_data.content:
                    thinking_content = span_data.content
                elif hasattr(span_data, 'prompt') and span_data.prompt:
                    thinking_content = span_data.prompt
                
                if thinking_content:
                    # 通过单独的消息类型发送Agent思考内容
                    asyncio.create_task(manager.send_log(
                        client_id, 
                        thinking_content, 
                        level="agent_thinking"
                    ))
                return None
            else:
                # 其他 Span 类型暂时只记录到服务器日志，不发送到前端
                logger.debug(f"[WebSocketTracer] Skipping span type: {span_type_name} for client {client_id}")
                return None
                
            # 返回格式化的普通消息 (如果适用)
            return {"message": message, "level": level}
        except Exception as e:
            logger.error(f"格式化消息时出错: {e}")
            return None
    
    def on_span_end(self, span: Span[Any]) -> None:
        client_id, manager, _ = self._get_client_manager(span)
        if not client_id or not manager:
            return

        try:
            formatted = self._format_message(span, client_id)
            if formatted:
                 # 发送格式化的消息
                 asyncio.create_task(manager.send_log(client_id, formatted["message"], level=formatted["level"]))
        except Exception as e:
            logger.error(f"处理span_end事件时出错: {e}")

    def on_trace_start(self, trace: Trace) -> None: 
        client_id, manager, _ = self._get_client_manager(trace)
        if not client_id or not manager:
            return
            
        try:
            logger.debug(f"[GlobalWebSocketTracer] Trace Start: {getattr(trace, 'trace_id', 'N/A')} for client {client_id}")
        except Exception as e:
            logger.error(f"处理trace_start事件时出错: {e}")
            
    def on_trace_end(self, trace: Trace) -> None: 
        client_id, manager, _ = self._get_client_manager(trace)
        if not client_id or not manager:
            return
            
        try:
            logger.debug(f"[GlobalWebSocketTracer] Trace End: {getattr(trace, 'trace_id', 'N/A')} for client {client_id}")
            
            # 自动注销完成的trace
            self.unregister(getattr(trace, 'trace_id', None))
            
            # 周期性清理过期路由
            if random.random() < 0.1:  # 10%概率执行清理
                self.cleanup_expired_routes()
        except Exception as e:
            logger.error(f"处理trace_end事件时出错: {e}")
            
    def on_span_start(self, span: Span[Any]) -> None: 
        client_id, manager, _ = self._get_client_manager(span)
        if not client_id or not manager:
            return
            
        try:
            logger.debug(f"[GlobalWebSocketTracer] Span Start: {getattr(span, 'span_id', 'N/A')} for client {client_id}")
        except Exception as e:
            logger.error(f"处理span_start事件时出错: {e}")
            
    def shutdown(self) -> None:
        # 清空所有路由
        with self.lock:
            self.routes.clear()
            
    def force_flush(self) -> None:
        pass


# ---------------- 全局文件日志追踪处理器 ----------------
class GlobalFileTracingProcessor(TracingProcessor):
    """全局文件追踪处理器，内部路由到具体日志处理器"""
    def __init__(self):
        self.routes = {}  # {trace_id: (log_handler, timestamp)}
        self.lock = threading.Lock()
        self.cleanup_threshold = 3600  # 1小时未活动的路由将被清理
        logger.info("[GlobalFileTracingProcessor] 初始化")
    
    def register(self, trace_id: str, log_handler: logging.FileHandler):
        """注册一个新的trace_id到特定日志处理器"""
        with self.lock:
            self.routes[trace_id] = (log_handler, time.time())
        logger.info(f"[GlobalFileTracingProcessor] 注册trace_id: {trace_id}")
    
    def unregister(self, trace_id: str):
        """注销一个trace_id"""
        with self.lock:
            if trace_id in self.routes:
                del self.routes[trace_id]
                logger.info(f"[GlobalFileTracingProcessor] 注销trace_id: {trace_id}")
    
    def _get_log_handler(self, obj) -> Tuple[logging.FileHandler, float]:
        """获取对应trace的日志处理器"""
        trace_id = getattr(obj, 'trace_id', None)
        if not trace_id:
            return None, 0
            
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
                del self.routes[trace_id]
                logger.info(f"[GlobalFileTracingProcessor] 清理过期路由: {trace_id}")
    
    def _log_trace(self, log_handler: logging.FileHandler, message: str, level=logging.INFO):
        try:
            formatter = logging.Formatter('[TRACE:%(levelname)s] %(asctime)s - %(message)s')
            record = logging.LogRecord(
                name='tracing', level=level, 
                pathname="", lineno=0, msg=message, 
                args=(), exc_info=None, func=""
            )
            # 手动添加时间戳，因为 FileHandler 可能不会自动格式化
            record.asctime = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
            formatted_message = formatter.format(record)
            # 直接写入，避免依赖 root logger 配置
            log_handler.stream.write(formatted_message + log_handler.terminator)
            log_handler.flush() # 确保写入
        except Exception as e:
            print(f"Error logging trace to file: {e}") # 打印到控制台以防日志系统本身出问题
            logger.error(f"Error logging trace to file: {e}", exc_info=True)
            
    def _format_span_details(self, span: Span[Any]) -> str:
        span_data = span.span_data
        details = {}
        if hasattr(span_data, 'tool_name'): details["Tool"] = span_data.tool_name
        elif hasattr(span_data, 'function_name'): details["Tool"] = span_data.function_name
        
        if hasattr(span_data, 'input'): 
            try: details["Input"] = json.dumps(span_data.input, ensure_ascii=False, default=str)
            except: details["Input"] = "[Cannot Serialize]"
            
        if hasattr(span_data, 'output'):
            try: details["Output"] = json.dumps(span_data.output, ensure_ascii=False, default=str)
            except: details["Output"] = "[Cannot Serialize]"
            
        if hasattr(span_data, 'error') and span_data.error: details["Error"] = str(span_data.error)
        
        return json.dumps(details, ensure_ascii=False) if details else ""

    def on_trace_start(self, trace: Trace) -> None:
        log_handler, _ = self._get_log_handler(trace)
        if not log_handler:
            return
            
        self._log_trace(log_handler, f"Trace Start: ID={getattr(trace, 'trace_id', 'N/A')}, Name={getattr(trace, 'name', '')}")

    def on_trace_end(self, trace: Trace) -> None:
        log_handler, _ = self._get_log_handler(trace)
        if not log_handler:
            return
            
        duration_str = "N/A"
        if hasattr(trace, 'end_time_ns') and hasattr(trace, 'start_time_ns') and trace.end_time_ns and trace.start_time_ns:
            try: duration_ms = (trace.end_time_ns - trace.start_time_ns) / 1_000_000; duration_str = f"{duration_ms:.2f}ms"
            except: duration_str = "ErrorCalculatingDuration"
        
        self._log_trace(log_handler, f"Trace End: ID={getattr(trace, 'trace_id', 'N/A')}, Duration={duration_str}")
        
        # 自动注销完成的trace
        self.unregister(getattr(trace, 'trace_id', None))
        
        # 周期性清理过期路由
        if random.random() < 0.1:  # 10%概率执行清理
            self.cleanup_expired_routes()
    
    def on_span_start(self, span: Span[Any]) -> None:
        log_handler, _ = self._get_log_handler(span)
        if not log_handler:
            return
            
        span_type = type(span.span_data).__name__
        self._log_trace(log_handler, f"Span Start: ID={getattr(span, 'span_id', 'N/A')}, Type={span_type}, Parent={getattr(span, 'parent_id', 'N/A')}")

    def on_span_end(self, span: Span[Any]) -> None:
        log_handler, _ = self._get_log_handler(span)
        if not log_handler:
            return
            
        span_type = type(span.span_data).__name__
        duration_ms_str = "N/A"
        if hasattr(span, 'duration_ms') and span.duration_ms is not None:
             try: duration_ms_str = f"{span.duration_ms:.2f}ms"
             except: duration_ms_str = "ErrorCalculatingDuration"
        
        details_str = self._format_span_details(span)        
        msg = f"Span End: ID={getattr(span, 'span_id', 'N/A')}, Type={span_type}, Duration={duration_ms_str}" 
        if details_str: msg += f", Details: {details_str}"
        self._log_trace(log_handler, msg)
    
    def shutdown(self) -> None:
        # 清空所有路由
        with self.lock:
            self.routes.clear()
            
    def force_flush(self) -> None:
        # 强制刷新所有活跃的日志处理器
        with self.lock:
            for trace_id, (log_handler, _) in self.routes.items():
                if log_handler:
                    try:
                        log_handler.flush()
                    except:
                        pass
                        
# 创建全局处理器实例
global_ws_processor = GlobalWebSocketTracingProcessor()
global_file_processor = GlobalFileTracingProcessor()


# --- Tenacity 重试配置 ---
def check_code(value):
    return value.status_code in [429]

# 定义一个自定义的等待策略
def custom_wait_strategy(retry_state):
    """自定义等待策略，对429错误使用固定40秒，其他使用指数退避"""

    # 对其他错误使用指数退避策略
    exp_delay = min(1 * (2 ** (retry_state.attempt_number+1)), 30)
    randomized_delay = exp_delay * (0.75 + (random.random() * 0.5))  # 添加25%的随机抖动
    return randomized_delay


# 定义单一重试策略（不再分开处理不同类型的错误）
unified_retry = retry(
    retry=retry_if_result(check_code),
    wait=custom_wait_strategy,  # 使用自定义等待策略
    stop=stop_after_attempt(5), # 最多重试5次
    reraise=True,              # 重新抛出原始异常
    before_sleep=lambda retry_state: logger.warning(
        f"准备第{retry_state.attempt_number}次重试, "
        f"将等待{retry_state.next_action.sleep}秒"
    )
)

class CustomRetryTransport(httpx.AsyncHTTPTransport):
    """自定义HTTP传输层，添加重试机制"""
    
    @unified_retry
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """处理异步HTTP请求，添加重试功能"""
        response = await super().handle_async_request(request)
        return response
            

# --- 自定义 HTTP 客户端 ---

def CustomRetryClient(**kwargs) -> httpx.AsyncClient:
    """创建一个配置了自定义重试 Transport 的 httpx 客户端"""
    # 可以传递其他 httpx.AsyncClient 参数，例如 timeout
    # 确保传递的 timeout 不是 NotGiven 类型
    timeout = kwargs.pop('timeout', httpx.Timeout(60.0)) # 默认60秒超时
    limits = kwargs.pop('limits', httpx.Limits(max_connections=100, max_keepalive_connections=20))
    
    return httpx.AsyncClient(
        transport=CustomRetryTransport(), 
        timeout=timeout,
        limits=limits,
        **kwargs # 传递任何额外的 httpx 参数
    )

if __name__ == "__main__":
    pass