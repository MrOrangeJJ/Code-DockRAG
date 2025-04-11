#!/usr/bin/env python3
import os
import sys
import pandas as pd
import lancedb
import argparse
from lancedb.embeddings import EmbeddingFunctionRegistry
from lancedb.pydantic import LanceModel, Vector
from dotenv import load_dotenv
import logging # 导入日志库
import numpy as np # 导入numpy用于分块
from . import custom_embeddings
import time
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

root_dir = str(Path(os.path.dirname(os.path.abspath(__file__))).parent)
env_path = os.path.join(root_dir, '.env')
load_dotenv(env_path)

custom_tokenizer = custom_embeddings.register_custom_embeddings()

registry = EmbeddingFunctionRegistry.get_instance()
# 使用我们自定义的嵌入向量生成器
model = registry.get("custom-embeddings").create()
EMBEDDING_DIM = model.ndims()

# 使用tokenizer中的max_tokens替代环境变量
MAX_TOKENS = custom_tokenizer.max_tokens
logger.info(f"使用嵌入模型最大token限制: {MAX_TOKENS}")


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

def get_special_files(directory):
    md_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            pass
            # if file.endswith(('.md', '.sh')):
            #     full_path = os.path.join(root, file)
            #     md_files.append(full_path)
    return md_files

def process_special_files(md_files):
    contents = {}
    for file_path in md_files:
        with open(file_path, 'r', encoding='utf-8') as file:
            contents[file_path] = file.read()  # Store the content against the file path
    return contents

def create_markdown_dataframe(markdown_contents, max_tokens=None):
    """
    从markdown内容创建DataFrame
    
    Args:
        markdown_contents: 包含markdown内容的字典
        max_tokens: 可选的最大token数，默认使用tokenizer的max_tokens
        
    Returns:
        包含格式化后的markdown内容的DataFrame
    """
    # Create a DataFrame from markdown_contents dictionary
    df = pd.DataFrame(list(markdown_contents.items()), columns=['file_path', 'source_code'])
    
    # Format the source_code with file information and apply clipping
    df['source_code'] = df.apply(
        lambda row: f"File: {row['file_path']}\n\nContent:\n{clip_text_to_max_tokens(row['source_code'])}\n\n", 
        axis=1
    )
    
    # Add placeholder "empty" for the other necessary columns
    for col in ['class_name', 'constructor_declaration', 'method_declarations', 'references']:
        df[col] = "empty"
    return df


class Method(LanceModel):
    code: str = model.SourceField()
    method_embeddings: Vector(EMBEDDING_DIM) = model.VectorField()
    file_path: str
    class_name: str
    name: str
    doc_comment: str
    source_code: str
    references: str

class Class(LanceModel):
    source_code: str = model.SourceField()
    class_embeddings: Vector(EMBEDDING_DIM) = model.VectorField()
    file_path: str
    class_name: str
    constructor_declaration: str
    method_declarations: str
    references: str

def clip_text_to_max_tokens(text, max_tokens=None):
    """使用tokenizer的detokenize_to_max_tokens方法截断文本"""
    return custom_tokenizer.detokenize_to_max_tokens(text, max_tokens)


def check_and_filter_token_limits(df, text_column, max_tokens=None, context_info_cols=None):
    """
    检查DataFrame中文本列的token数，并过滤掉超限条目
    
    Args:
        df: 数据DataFrame
        text_column: 包含文本的列名
        max_tokens: 最大token数，默认使用tokenizer的max_tokens
        context_info_cols: 用于日志记录的上下文信息列名列表
    
    Returns:
        (过滤后的DataFrame, 丢弃的条目数)
    """
    # 使用tokenizer的max_tokens作为默认值
    if max_tokens is None:
        max_tokens = custom_tokenizer.max_tokens
    else:
        max_tokens = int(max_tokens)
    
    # 确保context_info_cols不为None
    if context_info_cols is None:
        context_info_cols = []
        
    original_count = len(df)
    indices_to_drop = []
    
    for index, row in df.iterrows():
        text = row[text_column]
        token_count = custom_tokenizer.get_token_count(text)
        
        if token_count > max_tokens:
            context_info = {col: row[col] for col in context_info_cols if col in row}
            logger.warning(f"Token限制超标将被丢弃 ({token_count}/{max_tokens}): {context_info}")
            indices_to_drop.append(index)
            
    if indices_to_drop:
        df_filtered = df.drop(indices_to_drop)
        dropped_count = len(indices_to_drop)
        logger.info(f"已丢弃 {dropped_count} 个因token超限的条目。剩余 {len(df_filtered)} 条。")
        return df_filtered, dropped_count
    else:
        logger.info(f"所有条目的token数均在限制 ({max_tokens}) 内。")
        return df, 0

def add_data_in_batches(table, data_df):
    """
    将DataFrame数据添加到LanceDB表中
    嵌入向量生成器会在内部自动处理批次
    
    Args:
        table: LanceDB表对象
        data_df: 包含数据的DataFrame
    """
    if data_df is None or data_df.empty:
        logger.warning(f"没有数据可以添加到表 '{table.name}'")
        return
        
    logger.info(f"开始添加数据到表 '{table.name}' (共 {len(data_df)} 条记录)...")
    
    try:
        start_time = time.time()
        # 直接添加所有数据，嵌入向量生成器会在内部处理批次
        table.add(data_df)
        elapsed_time = time.time() - start_time
        logger.info(f"所有数据添加完成，耗时: {elapsed_time:.2f}秒")
    except Exception as e:
        logger.error(f"添加数据到表 '{table.name}' 失败: {e}", exc_info=True)
        raise

def run_create_tables(code_path, codebase_name=None, database_dir=None, processed_dir=None):
    """
    直接运行创建表的功能，可以从其他Python模块调用
    
    Args:
        code_path: 代码库路径
        codebase_name: 代码库名称（可选）
        processed_dir: 处理数据目录（可选）
        database_dir: 数据库目录（可选）
        
    Returns:
        bool: 是否成功
    """
    try:
        logger.info(f"开始为 {code_path} 创建数据库表...")
        
        # 获取表名和路径
        table_name, input_directory, database_uri = get_input_directories(
            code_path, codebase_name, processed_dir, database_dir
        )
        
        # 读取方法和类数据文件
        method_data_file = os.path.join(input_directory, "method_data.csv")
        class_data_file = os.path.join(input_directory, "class_data.csv")

        try:
            method_data = pd.read_csv(method_data_file)
            class_data = pd.read_csv(class_data_file)
        except FileNotFoundError as e:
            logger.error(f"错误: 未找到CSV文件 - {e}")
            logger.error(f"请先运行 preprocessing.py 为代码库 '{code_path}' 生成数据.")
            return False

        special_files = get_special_files(code_path)
        special_contents = process_special_files(special_files)

        logger.info(f"原始方法数据条目数: {len(method_data)}")
        logger.info(f"原始类数据条目数: {len(class_data)}")

        # 连接到数据库
        db = lancedb.connect(database_uri)
        
        try:
            # --- 处理方法数据 ---
            logger.info("开始处理方法数据...")
            table = db.create_table(
                table_name + "_method", 
                schema=Method, 
                mode="overwrite",
                on_bad_vectors='drop'
            )

            # 确保'code'列是source_code的副本并处理类型
            method_data['code'] = method_data['source_code'].astype(str)
            
            null_rows = method_data.isnull().any(axis=1)
            if null_rows.any():
                logger.warning("方法数据中发现空值，将替换为'empty'")
                method_data = method_data.fillna('empty')
            else:
                logger.info("方法数据中未发现空值")

            # 检查并过滤方法数据的token限制
            logger.info(f"检查并过滤方法数据的token限制...")
            method_data, dropped_methods_count = check_and_filter_token_limits(
                method_data, 'code', context_info_cols=['file_path', 'class_name', 'name']
            )
            
            # 分批添加方法数据，不再传递固定的BATCH_SIZE
            add_data_in_batches(table, method_data)
            logger.info("方法数据处理和添加完成")
        
            # --- 处理类数据 ---
            logger.info("开始处理类数据...")
            class_table = db.create_table(
                table_name + "_class", 
                schema=Class, 
                mode="overwrite",
                on_bad_vectors='drop'
            )
            
            null_rows = class_data.isnull().any(axis=1)
            if null_rows.any():
                logger.warning("类数据中发现空值，将替换为空字符串''")
                class_data = class_data.fillna('')
            else:
                logger.info("类数据中未发现空值")

            processed_class_source_code = []
            class_exceeded_info = []
            
            for index, row in class_data.iterrows():
                file_path_str = str(row['file_path'])
                class_name_str = str(row['class_name'])
                source_code_str = str(row['source_code'])
                
                formatted_text = f"File: {file_path_str}\n\nClass: {class_name_str}\n\nSource Code:\n{source_code_str}\n\n"
                clipped_text = clip_text_to_max_tokens(formatted_text)
                processed_class_source_code.append(clipped_text)
                
                # 记录截断发生
                if len(clipped_text) < len(formatted_text):
                    original_token_count = custom_tokenizer.get_token_count(formatted_text)
                    logger.info(f"类文本被截断: 文件='{file_path_str}', 类='{class_name_str}' (原始 {original_token_count} tokens)")
                    class_exceeded_info.append({'file': file_path_str, 'class': class_name_str, 'tokens': original_token_count})

            class_data['source_code'] = processed_class_source_code
            
            if class_exceeded_info:
                logger.info(f"共发现 {len(class_exceeded_info)} 个类的source_code（格式化后）因超过token限制而被截断。")
            else:
                logger.info("所有类的source_code（格式化后）token数均在限制内")

            # add after something because chance class_data may be empty
            if class_data.empty:
                logger.warning("类数据为空，将创建一个包含占位符的条目")
                columns = ['source_code', 'file_path', 'class_name', 'constructor_declaration', 'method_declarations', 'references']
                empty_data = {col: ["empty"] for col in columns}
                class_data = pd.DataFrame(empty_data)
                
            # 分批添加类数据
            add_data_in_batches(class_table, class_data)
            logger.info("类数据添加完成")

            # --- 处理特殊文件 ---
            if len(special_contents) > 0:
                logger.info("开始处理特殊文件...")
                markdown_df = create_markdown_dataframe(special_contents)
                
                # 检查并过滤特殊文件的token限制
                logger.info(f"检查并过滤特殊文件的token限制...")
                markdown_df, dropped_special_count = check_and_filter_token_limits(
                    markdown_df, 'source_code', context_info_cols=['file_path']
                )
                    
                # 分批添加特殊文件数据
                add_data_in_batches(class_table, markdown_df)
                logger.info("特殊文件添加完成")
            else:
                logger.info("没有特殊文件需要处理")

            logger.info(f"所有数据处理和嵌入完成，共添加: {len(method_data)} 个方法, {len(class_data)} 个类")
            return True

        except Exception as e:
            logger.error(f"处理数据库表时发生严重错误: {e}", exc_info=True)
            # 尝试删除可能创建了一半的表
            try:
                if table_name + "_method" in db.table_names():
                    db.drop_table(table_name + "_method")
                    logger.info(f"已删除表: {table_name + '_method'}")
                if table_name + "_class" in db.table_names():
                    db.drop_table(table_name + "_class")
                    logger.info(f"已删除表: {table_name + '_class'}")
            except Exception as drop_e:
                logger.error(f"删除表时发生错误: {drop_e}")
            # 返回错误状态
            return False
            
    except Exception as e:
        logger.error(f"创建数据库表过程中出错: {e}", exc_info=True)
        return False
    finally:
        logger.info("数据库操作完成")

if __name__ == "__main__":
    pass