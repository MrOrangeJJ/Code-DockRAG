"""
utils.py - 通用工具函数
提供代码库搜索系统中使用的通用工具函数
"""

import os
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Tuple
from dotenv import load_dotenv
import re
import json
from .constants import RECOGNIZABLE_FILES
from .constants import STRONG_SEARCH_SUPPORTED_LANGUAGES, BLACKLIST_DIR, BLACKLIST_FILES, WHITELIST_FILES
import asyncio
from threading import Lock

# 加载环境变量 - 指定.env文件的绝对路径
# 获取项目根目录（即code_dock的父目录）
root_dir = str(Path(os.path.dirname(os.path.abspath(__file__))).parent)
env_path = os.path.join(root_dir, '.env')
load_dotenv(env_path)

# 配置日志
logger = logging.getLogger(__name__)

CODEBASE_CONFIG = {}
CODEBASE_CONFIG_LOCK = Lock()

def get_codebase_path(codebase_name: str) -> Dict[str, str]:
    """
    获取代码库的各个路径
    
    Args:
        codebase_name: 代码库名称
        
    Returns:
        包含代码库各个路径的字典
    """
    # 使用.env中定义的CODEBASE_PATH作为基础路径
    codebase_path = os.getenv("CODEBASE_PATH", "codebases")
    base_path = Path(codebase_path) / codebase_name
    
    return {
        "base": str(base_path),
        "code": str(base_path / "code"),
        "database": str(base_path / "database"),
        "processed": str(base_path / "processed")
    }

def ensure_directories(paths: Dict[str, str]) -> None:
    """
    确保所需的目录结构存在
    
    Args:
        paths: 包含代码库各路径的字典
    """
    # 检查是否需要自动创建目录

    for path in paths.values():
        os.makedirs(path, exist_ok=True)
        logger.info(f"确保目录存在: {path}")


def get_language_from_extension(file_ext):
    """
    从文件扩展名获取对应的语言枚举
    
    Args:
        file_ext: 文件扩展名（如.py, .java等）
        
    Returns:
        对应的LanguageEnum值，如果不支持则返回None
    """
    # 导入这里避免循环导入
    from .treesitter import LanguageEnum
    
    FILE_EXTENSION_LANGUAGE_MAP = {
        ".java": LanguageEnum.JAVA,
        ".py": LanguageEnum.PYTHON,
        ".js": LanguageEnum.JAVASCRIPT,
        ".rs": LanguageEnum.RUST,
        # Add other extensions and languages as needed
    }
    return FILE_EXTENSION_LANGUAGE_MAP.get(file_ext)

def is_valid_codebase(directory_path: str) -> bool:
    """
    检查目录是否包含WHITELIST_FILES中列出的文件
    
    Args:
        directory_path: 要检查的目录路径
        
    Returns:
        bool: 如果目录包含至少一个whitelist中的文件则返回True
    """
    
    if not os.path.exists(directory_path) or not os.path.isdir(directory_path):
        return False
        
    # 遍历目录中的所有文件和子目录
    for root, dirs, files in os.walk(directory_path):
        # 检查精确匹配的文件
        for file in files:
            if file in RECOGNIZABLE_FILES:
                return True
                
        # 检查.git目录
        if ".git" in dirs:
            return True
            
        # 检查文件扩展名
        for file in files:
            for pattern in RECOGNIZABLE_FILES:
                if pattern.startswith("*.") and file.endswith(pattern[1:]):
                    return True
    
    return False

def read_file_safely(file_path: str, encoding: str = 'utf-8') -> str:
    """
    安全地读取文件内容，处理编码错误
    
    Args:
        file_path: 文件路径
        encoding: 编码方式，默认utf-8
        
    Returns:
        文件内容字符串
    """
    try:
        with open(file_path, 'r', encoding=encoding, errors='replace') as file:
            content = file.read()
            # 检查是否是二进制文件或包含太多无法解码的字符
            if '\ufffd' in content and content.count('\ufffd') > len(content) * 0.1:
                return ""
            return content
    except Exception as e:
        logger.error(f"读取文件 {file_path} 内容时出错: {e}")
        return f"错误: 读取文件内容时出错: {str(e)}"


def init_config_file(codebase_name: str):
    config = {
        "project_type": "unknown",
        "analyzer_ready": False,
        
        "ignore_dirs": BLACKLIST_DIR,
        "ignore_files": BLACKLIST_FILES,
        "whitelist_files": WHITELIST_FILES,
    }
    ensure_directories(get_codebase_path(codebase_name))
    update_config_file(codebase_name, config, override=True)

def load_config_file(codebase_name: str, key: str = None) -> Dict[str, Any]:
    """
    加载配置文件
    """

    global CODEBASE_CONFIG
    if codebase_name in CODEBASE_CONFIG:
        config = CODEBASE_CONFIG[codebase_name]
    else:
        config_path = os.path.join(get_codebase_path(codebase_name)["processed"], "config.json")
        if not os.path.exists(config_path):
            init_config_file(codebase_name)
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
    
        CODEBASE_CONFIG[codebase_name] = config

    if key:
        if key in config:
            return config[key]
        else:
            return None
    else:
        return config
    
    
def update_config_file(codebase_name: str, config: Dict[str, Any], override: bool = False, mark_dirty: bool = True):
    """
    更新配置文件
    """
    # global CODEBASE_CONFIG_LOCK
    # with CODEBASE_CONFIG_LOCK:
    global CODEBASE_CONFIG
    config_path = os.path.join(get_codebase_path(codebase_name)["processed"], "config.json")
    
    if override:
        current_config = {}
    else:
        current_config = load_config_file(codebase_name)
    current_config.update(config)
    
    CODEBASE_CONFIG[codebase_name] = current_config

    if mark_dirty:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(current_config, f, ensure_ascii=False, indent=4)



def detect_project_language(codebase_name: str) -> str:
    """
    检测项目的主要编程语言类型，基于文件数量统计
    
    Args:
        codebase_name: 代码库名称
        
    Returns:
        str: 项目的主要编程语言类型（如'python'、'java'等）
    """
    codebase_path = get_codebase_path(codebase_name)
    code_path = codebase_path["code"]
    
    # 初始化语言计数器
    language_counts = {lang: 0 for lang in STRONG_SEARCH_SUPPORTED_LANGUAGES.keys()}
    
    # 遍历项目目录
    for root, dirs, files in os.walk(code_path):
        # 过滤黑名单目录
        dirs[:] = [d for d in dirs if d not in load_config_file(codebase_name, "ignore_dirs")]
        
        # 统计每个文件的语言类型
        for file in files:
            file_ext = os.path.splitext(file)[1].lower()
            
            # 检查文件扩展名属于哪种语言
            for lang, extensions in STRONG_SEARCH_SUPPORTED_LANGUAGES.items():
                if file_ext in extensions:
                    language_counts[lang] += 1
                    break
    
    # 找出文件数量最多的语言
    max_count = 0
    dominant_language = "unknown"
    
    for lang, count in language_counts.items():
        if count > max_count:
            max_count = count
            dominant_language = lang
    
    return dominant_language


async def timeout_monitor(task, timeout):
    await asyncio.sleep(timeout)
    if not task.done():
        task.cancel()

def get_input_directories(code_path, codebase_name=None, processed_dir=None, database_dir=None):
    """
    获取输入和输出目录
    
    Args:
        code_path: 代码库路径
        codebase_name: 代码库名称（可选）
        processed_dir: 处理数据目录（可选）
        database_dir: 数据库目录（可选）
        
    Returns:
        (codebase_name, processed_dir, database_dir) 元组
    """
    # 如果未提供代码库名称，则从路径中推导
    if not codebase_name:
        # 归一化和获取绝对路径
        normalized_path = os.path.normpath(os.path.abspath(code_path))
        # 提取目录的基本名称
        parent_dir = os.path.dirname(normalized_path)
        codebase_name = os.path.basename(parent_dir)
        logger.info(f"从路径推导的代码库名称: {codebase_name}")
        
    # 获取环境变量中的代码库基础路径
    codebase_base = os.getenv("CODEBASE_PATH", "codebases")
    
    # 设置processed_dir
    if not processed_dir:
        processed_dir = os.path.join(codebase_base, codebase_name, "processed")
    logger.info(f"处理数据目录: {processed_dir}")
    os.makedirs(processed_dir, exist_ok=True)
    
    # 设置database_dir
    if not database_dir:
        database_dir = os.path.join(codebase_base, codebase_name, "database")
    logger.info(f"数据库目录: {database_dir}")
    os.makedirs(database_dir, exist_ok=True)
    
    return codebase_name, processed_dir, database_dir 

def load_lsp_cache(codebase_name: str) -> Dict[str, Any]:
    """
    加载分析器缓存
    """
    cache_path = os.path.join(get_codebase_path(codebase_name)["database"], "lsp_cache.json")
    with open(cache_path, 'r', encoding='utf-8') as f:
        return json.load(f)
    

def search_text(codebase_name: str, keyword: str):

    paths = get_codebase_path(codebase_name)
    code_dir = Path(paths["code"])
    msg = {
            "codebase_name": codebase_name,
            "keyword": keyword,
            "matched_files": [],
            "message": "",
            "count": 0
        }
    
    if not code_dir.exists():
        msg["message"] = f"代码库 '{codebase_name}' 不存在"
        return msg
    
    if not keyword or len(keyword.strip()) == 0:
        msg["message"] = "搜索关键词不能为空"
        return msg
    
    try:
        # 遍历代码库目录，搜索包含关键词的文件
        matched_files = []
        
        for root, dirs, files in os.walk(code_dir):
            # 跳过隐藏文件夹和BLACKLIST_DIR中的目录
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in load_config_file(codebase_name, "ignore_dirs")]
            
            for file in files:
                # 跳过过大的文件和二进制文件
                file_path = Path(root) / file
                try:
                    # 确保文件不太大（10MB以内）
                    if file_path.stat().st_size > 10 * 1024 * 1024:  # 10MB
                        continue
                    
                    # 读取文件内容并搜索关键词
                    content = read_file_safely(file_path)
                    if keyword in content:
                        # 获取相对路径
                        relative_path = file_path.relative_to(code_dir)
                        matched_files.append(str(relative_path))
                except Exception as e:
                    logger.warning(f"搜索文件 {file_path} 时出错: {e}")
                    continue
        msg = {
            "codebase_name": codebase_name,
            "keyword": keyword,
            "matched_files": matched_files,
            "message": "search success",
            "count": len(matched_files)
        }

        return msg
    except Exception as e:
        msg["message"] = f"搜索失败: {e}"
        return msg