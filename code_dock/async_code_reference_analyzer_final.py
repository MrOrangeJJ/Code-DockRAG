import os
import logging
import asyncio
from typing import Dict, List, Optional, Any, AsyncIterator, Tuple, Union
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from tqdm import tqdm
from copy import deepcopy

class CustomLogger(MultilspyLogger):
    """自定义日志记录器，实现MultilspyLogger接口"""
    def __init__(self, level=logging.ERROR):  # 默认使用ERROR级别，减少输出
        self.logger = logging.getLogger("multilspy")
        self.logger.setLevel(level)
        # 移除已有的处理器
        for hdlr in self.logger.handlers[:]:
            self.logger.removeHandler(hdlr)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s - %(message)s')  # 简化日志格式
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log(self, message, level=logging.INFO):
        # 丢弃低级别日志消息
        if level < self.logger.level:
            return
        self.logger.log(level, message)


class AsyncCodeReferenceAnalyzer:
    """异步代码引用分析器，使用LSP协议查找代码引用"""
    
    # 支持的语言类型
    SUPPORTED_LANGUAGES = {
        "java": (".java",),
        "python": (".py",),
        "typescript": (".ts", ".tsx"),
        "javascript": (".js", ".jsx"),
        "csharp": (".cs",),
        "go": (".go",),
        "rust": (".rs",),
        "kotlin": (".kt", ".kts"),
        "ruby": (".rb",),
        "dart": (".dart",)
    }
    
    def __init__(self, project_path: str, language_type: str, log_level=logging.WARNING, ignore_dirs=[]):
        """
        初始化异步代码引用分析器
        
        Args:
            project_path: 项目根目录的绝对路径
            language_type: 项目语言类型，必须是multilspy支持的语言之一
            log_level: 日志级别
            ignore_dirs: 要忽略的目录列表
        """
        self.ignore_dirs = ignore_dirs
        self.global_symbol_cache = {}
        # 设置日志
        self.analyzer_logger = logging.getLogger("code_analyzer")
        self.analyzer_logger.setLevel(log_level)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s - %(message)s')  # 简化日志格式
        handler.setFormatter(formatter)
        # 清除已有的处理器
        for hdlr in self.analyzer_logger.handlers[:]:
            self.analyzer_logger.removeHandler(hdlr)
        self.analyzer_logger.addHandler(handler)
        
        self.project_path = os.path.abspath(project_path)
        if not os.path.exists(self.project_path):
            raise ValueError(f"项目路径不存在: {self.project_path}")
            
        # 验证语言类型
        self.language_type = language_type.lower()
        if self.language_type not in self.SUPPORTED_LANGUAGES:
            supported = ", ".join(self.SUPPORTED_LANGUAGES.keys())
            raise ValueError(f"不支持的语言类型: {language_type}。支持的语言: {supported}")
        
        # 初始化日志记录器 - 设置更高的日志级别以减少输出
        multilspy_log_level = logging.ERROR  # 提高multilspy的日志级别以减少输出
        self.multilspy_logger = CustomLogger(multilspy_log_level)
        
        # 配置LSP客户端
        self.config = MultilspyConfig.from_dict({
            "code_language": self.language_type,
            "trace_lsp_communication": (log_level <= logging.DEBUG)  # 只有在DEBUG模式下才追踪LSP通信
        })
        
        self.analyzer_logger.info(f"初始化异步LSP客户端，语言类型: {self.language_type}, 项目路径: {self.project_path}")
        
        # 初始化LSP客户端（异步）
        self.lsp = None
        self._server_ctx_manager = None
        self.server_started = False
        
        # 初始化内部状态
        self.initialized = False
        self.project_files = []

    
    async def initialize(self):
        """异步初始化分析器，建立连接和扫描文件"""
        if self.initialized:
            return
            
        # 初始化LSP客户端
        try:
            self.lsp = LanguageServer.create(self.config, self.multilspy_logger, self.project_path)
            self.analyzer_logger.info("异步LSP客户端初始化成功")
        except Exception as e:
            self.analyzer_logger.error(f"异步LSP客户端初始化失败: {str(e)}")
            raise
        
        # 扫描项目文件
        self.analyzer_logger.info("开始扫描项目文件...")
        self.project_files = self._scan_project_files()
        self.analyzer_logger.info(f"扫描完成，发现 {len(self.project_files)} 个{self.language_type}文件")
        self.initialized = True

        await self.start_server()
        
    
    def _scan_project_files(self) -> List[str]:
        """扫描项目中所有符合语言类型的代码文件"""
        file_extensions = self.SUPPORTED_LANGUAGES[self.language_type]
        project_files = []
        
        for root, dirs, files in os.walk(self.project_path):
            # 跳过忽略的目录
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]
            
            # 如果路径包含需要忽略的目录，则跳过
            if any(ignore_dir in root.split(os.sep) for ignore_dir in self.ignore_dirs):
                continue
                
            for file in files:
                if file.endswith(file_extensions):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, self.project_path)
                    project_files.append(rel_path)
        
        return project_files
    
    async def start_server(self):
        """异步启动LSP服务器"""
        if not self.initialized:
            await self.initialize()
            
        if not self.server_started:
            try:
                self._server_ctx_manager = self.lsp.start_server()
                
                # 进入上下文
                await self._server_ctx_manager.__aenter__()
                
                # 标记服务器已启动
                self.server_started = True
                self.analyzer_logger.info("LSP服务器启动成功")
            except Exception as e:
                error_msg = f"异步LSP服务器启动失败: {str(e)}"
                self.analyzer_logger.error(error_msg)
                raise ValueError(error_msg)
                
    async def load_workspace_symbols(self):
        """
        异步加载工作区中所有文件的符号信息，使用多线程提高并发处理性能
        
        Returns:
            int: 成功加载的文件数量
        """
        
        # 确保服务器已启动
        await self.start_server()
        self.global_symbol_cache = {}

        taskss = [self._load_file_symbols(file_path) for file_path in self.project_files]
        results = await asyncio.gather(*taskss)
        
            
        for result in results:
            if result is None:
                continue
            file_path, processed_symbols = result
            self.global_symbol_cache[file_path] = processed_symbols
        
        await self.close(force=True)
        await self.start_server()
        return self.global_symbol_cache
    

    async def _load_file_symbols(self, file_path):
        """
        异步加载单个文件的所有符号信息。
        注意：multilspy的request_document_symbols内部会处理文件的打开和关闭。
        
        Args:
            file_path: 文件相对路径
            
        Returns:
            dict: 处理后的符号信息，格式为 {符号名称: 符号信息}，失败时返回空字典
        """
        try:
            # 直接调用异步请求，multilspy内部会处理文件打开/关闭
            try:
                symbols, _ = await asyncio.wait_for(
                    self.lsp.request_document_symbols(file_path),
                    timeout=10.0
                )
                
                # print(self.project_path, file_path)
                # print(file_path)
                # symbols, _ = await self.lsp.request_document_symbols(file_path)
                if symbols is None or len(symbols) == 0:
                    return None
                
                # 处理符号树并返回结果
                processed_symbols = self._process_symbols(symbols)
                if processed_symbols:
                    self.analyzer_logger.debug(f"文件 {file_path} 加载了 {len(processed_symbols)} 个符号")
                return [file_path, processed_symbols]
            except asyncio.TimeoutError:
                return None
            except Exception as inner_e:
                # 捕获请求内部的错误
                return None
        except Exception as e:
            print(f"加载文件 {file_path} 符号失败: {str(e)}")
            return None
    
    def _process_symbols(self, symbols, parent_path=""):
        """
        处理符号树，将其扁平化为路径->位置的映射
        
        Args:
            symbols: 符号树
            parent_path: 父级符号路径
            
        Returns:
            dict: 扁平化的符号表，格式为 {符号名称: 符号信息}
        """
        # 这个函数是同步的，处理已获取的符号数据
        result = {}
        
        for symbol in symbols:
            symbol_name = symbol.get("name", "")
            symbol_kind = symbol.get("kind", "")
            
            # 构建符号完整路径（支持嵌套符号）
            full_path = f"{parent_path}.{symbol_name}" if parent_path else symbol_name
            
            # 存储符号范围信息
            result[full_path] = {
                "range": symbol.get("range", {}),
                "selectionRange": symbol.get("selectionRange", {}),
                "kind": symbol_kind
            }
            
            # 递归处理子符号
            if "children" in symbol and symbol["children"]:
                child_symbols = self._process_symbols(symbol["children"], full_path)
                result.update(child_symbols)
        
        return result

    async def correct_find_references(self, file_path, symbol_name, symbol_type=None, use_cache=True):
        formatted_refs = []
        # 确保已初始化
        if not self.initialized:
            return file_path, symbol_name, []
            
        rel_path = file_path
        
        if use_cache and rel_path in self.global_symbol_cache:
            file_symbols = self.global_symbol_cache[rel_path]
        else:
            temp = await self._load_file_symbols(rel_path)
            if temp:
                file_symbols = temp[1]
                self.global_symbol_cache[rel_path] = file_symbols
            else:
                file_symbols = {}

        matching_symbol = symbol_name
        
        # 获取符号位置
        symbol_info = file_symbols[matching_symbol]
        
        # 优先使用selectionRange，如果没有则使用range
        position = (symbol_info.get("selectionRange", {}).get("start") or 
                   symbol_info.get("range", {}).get("start", {}))
        
        line = position.get("line", 0)
        character = position.get("character", 0)
        
        # 异步请求引用
        try:
            # 使用上下文管理器打开文件
            file_context = self.lsp.open_file(rel_path)
            file_context.__enter__()
            
            try:
                references = await self.lsp.request_references(rel_path, line, character)
                if references is None:
                    references = []
            finally:
                # 确保文件被关闭
                file_context.__exit__(None, None, None)
        except Exception as e:
            return file_path, symbol_name, []
        
        # 格式化引用结果
        for ref in references:
            # 处理引用URI
            ref_uri = ref.get("uri", "")
            if ref_uri.startswith("file://"):
                ref_path = ref_uri[7:]
                if ref_path.startswith("/") and ":" in ref_path[1:3]:
                    ref_path = ref_path[1:]
            else:
                ref_path = ref_uri
            
            # 相对化路径
            try:
                ref_file = os.path.relpath(ref_path, self.project_path)
            except ValueError:
                ref_file = ref_path
            
            ref_range = ref.get("range", {})
            
            # 获取代码片段
            snippet = await self._get_code_snippet(ref_file, ref_range)
            
            formatted_refs.append({
                "file_path": ref_file,
                "range": ref_range,
                "snippet": snippet
            })
        
        return file_path, symbol_name, formatted_refs
    
    
    async def _get_code_snippet(self, file_path: str, range_info: Dict) -> str:
        """异步获取指定范围的代码片段"""
        try:
            full_path = os.path.join(self.project_path, file_path)
            
            if not os.path.exists(full_path):
                return "文件不存在"
            
            # 使用异步文件IO读取文件
            async def read_file():
                # 使用run_in_executor将同步IO操作放在线程池中执行
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: open(full_path, 'r', encoding='utf-8').readlines())
                
            lines = await read_file()
            
            start_line = range_info.get("start", {}).get("line", 0)
            end_line = range_info.get("end", {}).get("line", start_line)
            
            # 确保行范围有效
            if start_line < 0 or start_line >= len(lines):
                return "行范围无效"
            
            # 提取代码片段
            if start_line == end_line:
                return lines[start_line].strip()
            else:
                return "".join(lines[start_line:end_line+1]).strip()
        except Exception as e:
            return f"获取代码片段错误: {str(e)}"
    
    async def close(self, force=False):
        """
        异步关闭LSP客户端连接，释放所有资源
        
        Args:
            timeout: 如果为0，则强制立即关闭不等待；如果为None，尝试优雅关闭；其他值为等待超时时间
        """
        if not self.server_started or not hasattr(self, '_server_ctx_manager'):
            return
            
        try:
            if force:
                await asyncio.wait_for(self._server_ctx_manager.__aexit__(None, None, None), timeout=5.0)
                if hasattr(self.lsp, 'server') and hasattr(self.lsp.server, 'process'):
                    process = self.lsp.server.process
                    if process and process.returncode is None:
                        try:
                            process.terminate()
                            self.analyzer_logger.info("LSP服务器进程已强制终止")
                        except Exception:
                            pass
                self.server_started = False
                return
                
            # 非强制关闭情况
            else:
                await self._server_ctx_manager.__aexit__(None, None, None)

        except Exception:
            # 发生任何错误，都确保标记为已关闭
            self.server_started = False
    # 实现上下文管理器协议
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize()
        if not self.server_started:
            await self.start_server()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()


    async def generate_all_references(self, progress_callback=None):
        await self.load_workspace_symbols()
        
        total_files = sum([len(x) for x in self.global_symbol_cache.values()])
        record = deepcopy(self.global_symbol_cache)

        bar = tqdm(total=total_files, desc="处理文件")
        progress = 0

        async def find_refs(file_path, symbol_name):
            nonlocal progress
            temp = await self.correct_find_references(file_path, symbol_name)
            progress += 1
            if progress_callback:
                progress_callback(progress / total_files)
            bar.update(1)
            return temp
    
        tasks = []
        for i in self.project_files:
            if i in self.global_symbol_cache:
                for j in self.global_symbol_cache[i]:
                    tasks.append(find_refs(i, j))


        results = await asyncio.gather(*tasks)
        for refs in results:
            if refs and len(refs[2]) > 0:
                record[refs[0]][refs[1]] = refs[2]

        return record

if __name__ == "__main__":
    async def main():
        # 示例用法
        analyzer = AsyncCodeReferenceAnalyzer(
            project_path=".",
            language_type="python"
        )
        
        try:
            # 使用异步上下文管理器
            async with analyzer:
                refs = await analyzer.find_references("async_code_reference_analyzer.py", "AsyncCodeReferenceAnalyzer")
                print(f"找到 {len(refs)} 个引用")
        except Exception as e:
            print(f"错误: {str(e)}")
    
    # 运行异步主函数
    asyncio.run(main())