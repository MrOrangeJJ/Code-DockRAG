#!/usr/bin/env python3
"""
search_app.py - 专注于代码库搜索功能的简化脚本
只执行RAG搜索并返回检索到的上下文，不进行LLM对话
"""

import os
import sys
import re
import argparse
import logging
from dotenv import load_dotenv
import lancedb
from lancedb.rerankers import AnswerdotaiRerankers
from openai import OpenAI
from . import custom_embeddings
from pathlib import Path

# 获取项目根目录（即code_dock的父目录）
root_dir = str(Path(os.path.dirname(os.path.abspath(__file__))).parent)
env_path = os.path.join(root_dir, '.env')
load_dotenv(env_path)

# 从prompts.py导入需要的提示模板
from .prompts import HYDE_SYSTEM_PROMPT, HYDE_V2_SYSTEM_PROMPT

# 日志设置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("HYDE_API_KEY"), base_url=os.getenv("HYDE_MODEL_BASE_URL"))

reranker = AnswerdotaiRerankers(column="source_code")

def setup_database(code_path, db_path=None, codebase_name=None):
    """设置数据库连接并打开表
    
    Args:
        code_path: 代码库路径
        db_path: 数据库路径（可选）
        codebase_name: 代码库名称（可选）
        
    Returns:
        (method_table, class_table) 元组
    """
    # 如果未提供代码库名称，从路径推导
    if not codebase_name:
        normalized_path = os.path.normpath(os.path.abspath(code_path))
        parent_dir = os.path.dirname(normalized_path)
        codebase_name = os.path.basename(parent_dir)
    
    logger.info(f"使用代码库: {codebase_name}")
    
    # 设置数据库路径
    if not db_path:
        db_path = os.path.join("codebases", codebase_name, "database")
    
    logger.info(f"数据库路径: {db_path}")
    
    # LanceDB连接
    db = lancedb.connect(db_path)
    
    try:
        method_table = db.open_table(f"{codebase_name}_method")
        class_table = db.open_table(f"{codebase_name}_class")
        return method_table, class_table
    except ValueError as e:
        logger.error(f"Error: {e}")
        logger.error(f"无法找到代码库 '{codebase_name}' 的索引表。请先运行索引脚本。")
        raise ValueError(f"数据库表不存在: {e}")

def openai_hyde(query, codebase_name=None):
    """生成HYDE假设性答案，用于优化搜索"""
    try:
        logger.info("生成HYDE假设性答案...")
        
        # 加载项目介绍（如果存在）
        project_description = ""
        if codebase_name:
            description_path = os.path.join("codebases", codebase_name, "processed", "project_description.txt")
            if os.path.exists(description_path):
                try:
                    with open(description_path, 'r', encoding='utf-8') as f:
                        project_description = f.read().strip()
                    logger.info(f"已加载{codebase_name}的项目介绍")
                except Exception as e:
                    logger.warning(f"读取项目介绍文件时出错: {e}")
        
        # 构建系统消息，加入项目介绍
        system_message = HYDE_SYSTEM_PROMPT
        if project_description:
            system_message = f"""You are an expert software engineer. Your task is to predict code that answers the given query.

Project Description:
{project_description}

Instructions:
1. Analyze the query carefully.
2. Think through the solution step-by-step.
3. Generate concise, idiomatic code that addresses the query.
4. Include specific method names, class names, and key concepts in your response.
5. If applicable, suggest modern libraries or best practices for the given task.
6. You may guess the language based on the context provided.

Output format: 
- Provide only the improved query or predicted code snippet.
- Do not include any explanatory text outside the code.
- Ensure the response is directly usable for further processing or execution."""
        
        # 使用环境变量配置的模型
        hyde_model = os.getenv("HYDE_MODEL", "gpt-4o-mini")
        chat_completion = client.chat.completions.create(
            model=hyde_model,
            messages=[
                {
                    "role": "system",
                    "content": system_message
                },
                {
                    "role": "user",
                    "content": f"Help predict the answer to the query: {query}",
                }
            ],
            max_tokens=400  # 限制token以加快速度
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        logger.error(f"生成HYDE答案时出错: {e}")
        return query  # 出错时回退到原始查询

def openai_hyde_v2(query, temp_context, hyde_query):
    """生成HYDE-V2改进的查询"""
    try:
        logger.info("生成HYDE-V2改进查询...")
        hyde_model = os.getenv("HYDE_MODEL", "gpt-4o-mini")
        chat_completion = client.chat.completions.create(
            model=hyde_model,
            messages=[
                {
                    "role": "system", 
                    "content": HYDE_V2_SYSTEM_PROMPT.format(query=query, temp_context=temp_context)
                },
                {
                    "role": "user",
                    "content": f"Predict the answer to the query: {hyde_query}",
                }
            ],
            max_tokens=768  # 限制token以加快速度
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        logger.error(f"生成HYDE-V2查询时出错: {e}")
        return hyde_query  # 出错时回退到第一阶段查询

def process_input(input_text):
    """处理输入文本，删除多余空白"""
    processed_text = input_text.replace('\n', ' ').replace('\t', ' ')
    processed_text = re.sub(r'\s+', ' ', processed_text)
    processed_text = processed_text.strip()
    
    return processed_text

def generate_context(query, method_table, class_table, rerank=False, codebase_name=None):
    """执行两阶段HYDE搜索并生成上下文"""
    logger.info(f"搜索查询: {query}")
    
    # 第一阶段：生成假设性答案，用于初步搜索
    hyde_query = openai_hyde(query, codebase_name)
    logger.info(f"HYDE查询: {hyde_query}")
    
    # 使用HYDE查询搜索初步结果
    method_docs = method_table.search(hyde_query).limit(5).to_pandas()
    class_docs = class_table.search(hyde_query).limit(5).to_pandas()
    
    # 合并初步结果作为临时上下文
    temp_context = '\n'.join(method_docs['code'].tolist() + class_docs['source_code'].tolist())

    # 第二阶段：使用初步结果生成改进的查询
    hyde_query_v2 = openai_hyde_v2(query, temp_context, hyde_query)
    logger.info(f"HYDE-V2查询: {hyde_query_v2}")
    
    # 使用改进的查询执行最终搜索
    method_search = method_table.search(hyde_query_v2)
    class_search = class_table.search(hyde_query_v2)
    
    # 可选的重排序
    if rerank:
        logger.info("应用重排序...")
        method_search = method_search.rerank(reranker)
        class_search = class_search.rerank(reranker)
    
    # 获取最终结果
    method_docs = method_search.limit(5).to_list()
    class_docs = class_search.limit(5).to_list()
    
    # 取前3个最相关的方法和类
    top_3_methods = method_docs[:3]
    methods_combined = "\n\n".join(f"File: {doc['file_path']}\nCode:\n{doc['code']}" for doc in top_3_methods)
    
    top_3_classes = class_docs[:3]
    classes_combined = "\n\n".join(f"File: {doc['file_path']}\nClass Info:\n{doc['source_code']} References: \n{doc['references']}  \n END OF ROW {i}" for i, doc in enumerate(top_3_classes))
    
    # 合并方法和类信息
    full_context = methods_combined + "\n---- CLASS INFORMATION ----\n" + classes_combined
    
    return {
        'query': query,
        'hyde_query': hyde_query,
        'hyde_query_v2': hyde_query_v2,
        'methods': top_3_methods,
        'classes': top_3_classes,
        'full_context': full_context
    }

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='代码库搜索工具 - 只返回RAG搜索结果')
    parser.add_argument('codebase_path', help='代码库的路径')
    parser.add_argument('query', help='搜索查询')
    parser.add_argument('--rerank', action='store_true', help='使用重排序提高结果相关性')
    parser.add_argument('--raw', action='store_true', help='只输出原始内容，无格式化')
    parser.add_argument('--db-path', help='数据库路径（可选）')
    parser.add_argument('--codebase-name', help='代码库名称（可选）')
    args = parser.parse_args()
    
    # 设置数据库连接
    method_table, class_table = setup_database(
        args.codebase_path, 
        db_path=args.db_path,
        codebase_name=args.codebase_name
    )
    
    # 获取代码库名称，若未提供则从路径推导
    codebase_name = args.codebase_name
    if not codebase_name:
        # 从路径推导代码库名称
        normalized_path = os.path.normpath(os.path.abspath(args.codebase_path))
        parent_dir = os.path.dirname(normalized_path)
        codebase_name = os.path.basename(parent_dir)
    
    # 生成搜索上下文
    context_data = generate_context(args.query, method_table, class_table, args.rerank, codebase_name)
    
    # 输出结果
    if args.raw:
        print(context_data['full_context'])
    else:
        print("\n" + "="*80)
        print(f"原始查询: {args.query}")
        print(f"HYDE查询: {context_data['hyde_query']}")
        print(f"HYDE-V2查询: {context_data['hyde_query_v2']}")
        print("="*80)
        
        print("\n找到的方法:")
        for i, method in enumerate(context_data['methods']):
            print(f"\n--- 方法 {i+1} ---")
            print(f"文件: {method['file_path']}")
            print(f"类名: {method['class_name']}")
            print(f"方法名: {method['name']}")
            print("\n代码片段:")
            print("-"*40)
            print(method['code'])
            print("-"*40)
        
        print("\n找到的类:")
        for i, class_info in enumerate(context_data['classes']):
            print(f"\n--- 类 {i+1} ---")
            print(f"文件: {class_info['file_path']}")
            print(f"类名: {class_info['class_name']}")
            print("\n代码片段:")
            print("-"*40)
            print(class_info['source_code'])
            print("-"*40)
            
        print("\n" + "="*80)
        print("完整上下文:")
        print(context_data['full_context'][:1000] + "...(截断)")
        print("="*80)

if __name__ == "__main__":
    main() 