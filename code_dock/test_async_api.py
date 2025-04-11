#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import asyncio
import logging
from .async_code_reference_analyzer_final import AsyncCodeReferenceAnalyzer
import json
from copy import deepcopy
from tqdm import tqdm  
from concurrent.futures import ThreadPoolExecutor
from functools import partial

async def test_find_references(analyzer, test_file, symbol_name):
    print(f"\n====== 查找符号引用: '{symbol_name}' ======")
    start_time = time.time()
    

    refs = await analyzer.find_references(test_file, symbol_name)
    
    if refs["status"] == "success" or refs["status"] == "warning":
        if refs["message"]:
            print(f"提示信息: {refs['message']}")
        print(f"\n找到 {len(refs['result'])} 个引用:")
        for i, ref in enumerate(refs["result"]):
            file_path = ref["file_path"]
            line = ref["range"]
            print(f"{i+1}. 文件: {file_path}")
            print(f"   位置: {line}")
            print(f"   代码: {ref['snippet']}")
            print("-"*80)
    else:
        print(f"查找引用失败")
        print(f"错误信息: {refs['message']}")
    
    print(f"查找耗时: {time.time() - start_time:.2f}秒")
    return refs

async def main():
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    # 项目路径
    project_path = "/Users/tonyhuang/Desktop/base_code/ToneCreate/code"

    
    # 1. 初始化分析器
    print(f"\n====== 初始化异步代码引用分析器 ======")
    
    ignore_dirs = [
        'venv', 'env', '.venv', '.env',  # 虚拟环境
        '.git', '.svn',  # 版本控制
        'node_modules', 'bower_components',  # JS/TS依赖
        '__pycache__', '.pytest_cache', '.mypy_cache',  # Python缓存
        'dist', 'build',  # 构建目录
        'other'
    ]

    analyzer = AsyncCodeReferenceAnalyzer(
        project_path=project_path,
        language_type="java",
        log_level=logging.INFO,
        ignore_dirs=ignore_dirs
    )
    
    
    await analyzer.initialize()
    print(f"========= 1 =========")
    
    pj_files = analyzer.project_files
    print(len(pj_files))
    refs = await analyzer.generate_all_references()


    with open("record.json", "w") as f:
        json.dump(refs, f, ensure_ascii=False, indent=2)

    try:
        await analyzer.close()
        print("\n测试完成，资源已释放")
    except Exception as e:
        print(f"关闭错误: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 