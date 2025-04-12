#!/usr/bin/env python3
"""
indexer.py - 索引代码库的Python实现
替代原来的index_codebase.sh脚本，提供更灵活的调用方式
"""

import os
import sys
import logging
import shutil
import subprocess
from pathlib import Path
import json
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv
from .treesitter import generate_project_structure, save_project_structure
import asyncio
from .prompts import PROJECT_DESCRIPTION_QUERY
from .strong_search_agent import run_agent, set_tracing_disabled, set_trace_processors
from .utils import update_config_file, detect_project_language, timeout_monitor
from .async_code_reference_analyzer_final import AsyncCodeReferenceAnalyzer
import threading

# 导入通用工具函数
from .utils import get_codebase_path, ensure_directories, load_config_file

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Indexer")

# 获取项目根目录（即code_dock的父目录）
root_dir = str(Path(os.path.dirname(os.path.abspath(__file__))).parent)
env_path = os.path.join(root_dir, '.env')
load_dotenv(env_path)


def run_preprocessing(code_path: str, codebase_name: str, processed_dir: str) -> bool:
    """
    运行预处理步骤
    
    Args:
        code_path: 代码路径
        codebase_name: 代码库名称
        processed_dir: 处理结果目录
        
    Returns:
        bool: 是否成功
    """
    logger.info(f"开始对 {code_path} 运行预处理...")
    
    try:
        # 导入preprocessing模块中的函数
        from .preprocessing import process_codebase
        
        # 调用主函数进行处理
        success = process_codebase(codebase_name=codebase_name)
        
        if not success:
            logger.error("预处理失败")
            return False
        
        # 检查是否生成了预期的文件
        class_data_path = os.path.join(processed_dir, "class_data.csv")
        method_data_path = os.path.join(processed_dir, "method_data.csv")
        
        if not os.path.exists(class_data_path) or not os.path.exists(method_data_path):
            logger.error(f"预处理未生成预期的CSV文件: {class_data_path} 或 {method_data_path}")
            return False
            
        logger.info(f"预处理完成，已生成CSV文件")
        return True
        
    except ImportError as e:
        logger.error(f"无法导入preprocessing模块: {e}")
        return False
    except Exception as e:
        logger.error(f"预处理过程中出错: {e}")
        return False

async def generate_project_description(codebase_name: str, processed_dir: str) -> bool:
    """
    生成项目介绍并保存到processed目录
    
    Args:
        code_path: 代码路径
        processed_dir: 处理结果目录
        
    Returns:
        bool: 是否成功
    """
    code_path = get_codebase_path(codebase_name)["code"]
    logger.info(f"开始为 {code_path} 生成项目介绍...")
    
    try:
        import traceback
        import sys
        
        # 设置最大递归深度限制(可选)
        # 默认递归深度通常足够，但如果遇到大型代码库，可以适当增加
        # sys.setrecursionlimit(3000)  # 谨慎使用，可能导致栈溢出
        # 使用强搜索获取项目介绍
        try:

            result = await run_agent(codebase_name, PROJECT_DESCRIPTION_QUERY, tracing_disabled=True)
            
            if not result or "answer" not in result:
                logger.error("生成项目介绍失败，未获得有效回答")
                return False
            
            # 获取项目介绍内容
            project_description = result["answer"]
            
            # 保存到processed目录
            description_path = os.path.join(processed_dir, "project_description.txt")
            with open(description_path, "w", encoding="utf-8") as f:
                f.write(project_description)
            
            logger.info(f"项目介绍已保存至: {description_path}")
            return True
            
        except RecursionError as re:
            logger.error(f"生成项目介绍时遇到递归错误: {re}")
            logger.error(traceback.format_exc())
            
            # 递归错误时创建简单的默认介绍
            default_description = (
                "# 项目介绍\n\n"
                "这是一个代码项目，由于项目结构复杂，无法自动生成详细介绍。\n"
                f"项目路径: {code_path}\n"
                "请通过浏览代码库内容了解更多信息。"
            )
            
            # 保存默认介绍
            description_path = os.path.join(processed_dir, "project_description.txt")
            with open(description_path, "w", encoding="utf-8") as f:
                f.write(default_description)
                
            logger.info(f"已保存默认项目介绍至: {description_path}")
            return True  # 返回True以继续索引过程
            
    except ImportError as e:
        logger.error(f"无法导入运行强搜索所需模块: {e}")
        return False
    except Exception as e:
        logger.error(f"生成项目介绍过程中出错: {e}")
        logger.error(traceback.format_exc())
        
        # 创建简单的默认介绍
        try:
            default_description = (
                "# 项目介绍\n\n"
                "这是一个代码项目，由于技术原因，无法自动生成详细介绍。\n"
                f"项目路径: {code_path}\n"
                "请通过浏览代码库内容了解更多信息。"
            )
            
            # 保存默认介绍
            description_path = os.path.join(processed_dir, "project_description.txt")
            with open(description_path, "w", encoding="utf-8") as f:
                f.write(default_description)
                
            logger.info(f"已保存默认项目介绍至: {description_path}")
            return True  # 返回True以继续索引过程
        except Exception as write_err:
            logger.error(f"保存默认项目介绍时出错: {write_err}")
            return False

async def init_lsp_cache(codebase_name: str) -> bool:
    try:
        update_config_file(codebase_name, {"analyzer_progress": 0.0}, mark_dirty=False)
        project_type = load_config_file(codebase_name, "project_type")
        if project_type and project_type == "unknown":
            return False
        
        analyzer = AsyncCodeReferenceAnalyzer(
            project_path=get_codebase_path(codebase_name)["code"],
            language_type=project_type,
            log_level=logging.INFO,
            ignore_dirs=load_config_file(codebase_name, "ignore_dirs")
        )
        await analyzer.initialize()
        print("--------------------------------");
        print(analyzer.project_path)
        print(analyzer.language_type)
        print(len(analyzer.project_files))
        print("--------------------------------");
        
        def progress_callback(progress):
            print(f"progress: {progress}")
            update_config_file(codebase_name, {"analyzer_progress": progress}, mark_dirty=False)
        
        refs = await analyzer.generate_all_references(progress_callback=progress_callback)

        with open(os.path.join(get_codebase_path(codebase_name)["database"], "lsp_cache.json"), "w") as f:
            json.dump(refs, f, indent=2, ensure_ascii=False)


        if len(refs) > 0:
            update_config_file(codebase_name, {"analyzer_ready": True})
        await analyzer.close()
        return True
    
    except Exception as e:
        print(e)
        return False

    


def create_database_tables(code_path: str, codebase_name: str, database_dir: str, processed_dir: str) -> bool:
    """
    创建数据库表
    
    Args:
        code_path: 代码路径
        codebase_name: 代码库名称
        database_dir: 数据库目录
        processed_dir: 处理结果目录
        
    Returns:
        bool: 是否成功
    """
    logger.info(f"开始为 {code_path} 创建数据库表...")
    
    try:
        # 导入并运行create_tables模块中的run_create_tables函数
        from .create_tables import run_create_tables
        
        # 使用新函数创建表
        result = run_create_tables(
            code_path=code_path, 
            codebase_name=codebase_name,
            database_dir=database_dir,
            processed_dir=processed_dir
        )
        
        if result:
            logger.info("数据库表创建成功")
        else:
            logger.warning("数据库表创建过程中发生错误")
            
        return result
        
    except ImportError as e:
        logger.error(f"无法导入create_tables模块: {e}")
        return False
    except Exception as e:
        logger.error(f"创建数据库表过程中出错: {e}")
        return False
    


async def index_codebase(code_path: str) -> Tuple[bool, str]:
    """
    索引代码库的主函数，替代原来的index_codebase.sh脚本
    
    Args:
        code_path: 代码路径（完整路径）
        
    Returns:
        Tuple[bool, str]: (是否成功, 消息)
    """
    # 验证路径存在
    if not os.path.isdir(code_path):
        return False, f"目录不存在: {code_path}"
    
    # 获取代码库名称和路径
    parent_dir = os.path.dirname(code_path)
    codebase_name = os.path.basename(parent_dir)
    
    # 初始化analyzer_ready状态为False
    update_config_file(codebase_name, {"analyzer_ready": False})
    
    logger.info(f"开始索引代码库: {codebase_name}")
    logger.info(f"代码路径: {code_path}")
    
    # 获取路径
    paths = get_codebase_path(codebase_name)
    database_dir = paths["database"]
    processed_dir = paths["processed"]
    
    logger.info(f"数据库路径: {database_dir}")
    logger.info(f"处理路径: {processed_dir}")
    
    # 确保目录存在
    ensure_directories(paths)

    # 生成并保存项目结构
    structure_success = await asyncio.to_thread(generate_project_structure, codebase_name)
    # structure_success = generate_project_structure(codebase_name)
    update_config_file(codebase_name, {"project_type": detect_project_language(codebase_name)})

    task = asyncio.create_task(init_lsp_cache(codebase_name))
    asyncio.create_task(timeout_monitor(task, 1200))

    # 运行预处理
    await asyncio.to_thread(run_preprocessing, code_path, codebase_name, processed_dir)
    # preprocess_success = run_preprocessing(code_path, codebase_name, processed_dir)
    # if not preprocess_success:
    #     return False, "预处理失败"
    
    # 创建数据库表
    await asyncio.to_thread(create_database_tables, code_path, codebase_name, database_dir, processed_dir)
    # create_tables_success = create_database_tables(code_path, codebase_name, database_dir, processed_dir)
    # if not create_tables_success:
    #     return False, "创建数据库表失败"

    # 直接异步调用项目介绍生成函数
    description_success = await generate_project_description(codebase_name, processed_dir)
    
    # 即使项目结构生成或项目介绍生成失败，仍然返回成功，但附带警告
    message = f"代码库 {codebase_name} 索引成功"
    
    if not structure_success:
        message += "，但项目结构生成失败"
    
    if not description_success:
        message += "，但项目介绍生成失败"
    
    return True, message



if __name__ == "__main__":
    pass