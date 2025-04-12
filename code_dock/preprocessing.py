import os
import sys
import argparse
from .treesitter import Treesitter, LanguageEnum
from collections import defaultdict
import csv
from typing import List, Dict
from tree_sitter import Node
from tree_sitter_languages import get_language, get_parser
import logging

# 导入共享的常量和工具函数
from .constants import REFERENCE_IDENTIFIERS
from .utils import get_language_from_extension, read_file_safely, get_codebase_path, load_config_file

# 配置日志
logger = logging.getLogger(__name__)

def load_files(codebase_name):
    file_list = []
    codebase_path = get_codebase_path(codebase_name)["code"]
    for root, dirs, files in os.walk(codebase_path):
        dirs[:] = [d for d in dirs if d not in load_config_file(codebase_name, "ignore_dirs")]
        for file in files:
            file_ext = os.path.splitext(file)[1]
            if file_ext in load_config_file(codebase_name, "whitelist_files"):
                if file not in load_config_file(codebase_name, "ignore_files"):
                    file_path = os.path.join(root, file)
                    language = get_language_from_extension(file_ext)
                    if language:
                        file_list.append((file_path, language))

    return file_list

def parse_code_files(file_list):
    class_data = []
    method_data = []

    all_class_names = set()
    all_method_names = set()

    files_by_language = defaultdict(list)
    for file_path, language in file_list:
        files_by_language[language].append(file_path)

    for language, files in files_by_language.items():
        treesitter_parser = Treesitter.create_treesitter(language)
        for file_path in files:
            try:
                code = read_file_safely(file_path)
                if not code:  # 如果文件为空或读取失败，跳过
                    continue
                
                file_bytes = code.encode('utf-8')
                class_nodes, method_nodes = treesitter_parser.parse(file_bytes)

                # Process class nodes
                for class_node in class_nodes:
                    class_name = class_node.name
                    all_class_names.add(class_name)
                    class_data.append({
                        "file_path": file_path,
                        "class_name": class_name,
                        "constructor_declaration": "",  # Extract if needed
                        "method_declarations": "\n-----\n".join(class_node.method_declarations) if class_node.method_declarations else "",
                        "source_code": class_node.source_code,
                        "references": []  # Will populate later
                    })

                # Process method nodes
                for method_node in method_nodes:
                    method_name = method_node.name
                    all_method_names.add(method_name)
                    method_data.append({
                        "file_path": file_path,
                        "class_name": method_node.class_name if method_node.class_name else "",
                        "name": method_name,
                        "doc_comment": method_node.doc_comment,
                        "source_code": method_node.method_source_code,
                        "references": []  # Will populate later
                    })
            except Exception as e:
                logger.error(f"处理文件 {file_path} 时出错: {e}")
                continue

    return class_data, method_data, all_class_names, all_method_names

def find_references(file_list, class_names, method_names):
    references = {'class': defaultdict(list), 'method': defaultdict(list)}
    files_by_language = defaultdict(list)
    
    # Convert names to sets for O(1) lookup
    class_names = set(class_names)
    method_names = set(method_names)

    for file_path, language in file_list:
        files_by_language[language].append(file_path)

    for language, files in files_by_language.items():
        treesitter_parser = Treesitter.create_treesitter(language)
        for file_path in files:
            try:
                code = read_file_safely(file_path)
                if not code:  # 如果文件为空或读取失败，跳过
                    continue
                    
                file_bytes = code.encode('utf-8')
                tree = treesitter_parser.parser.parse(file_bytes)
                
                # Single pass through the AST
                stack = [(tree.root_node, None)]
                
                # 获取与语言相关的引用标识符
                lang_str = language.value
                ref_ids = REFERENCE_IDENTIFIERS.get(lang_str, {})
                if not ref_ids:
                    continue  # Skip if language not supported
                
                # 获取类和方法引用的类型
                class_ref_type = ref_ids.get('class')
                method_ref_type = ref_ids.get('method')
                child_field_name = ref_ids.get('child_field_name')
                
                while stack:
                    node, parent = stack.pop()
                    
                    # Check if node is a class reference
                    if node.type == class_ref_type and node.text.decode() in class_names:
                        class_name = node.text.decode()
                        references['class'][class_name].append(file_path)
                    
                    # Check if node is a method reference
                    if node.type == method_ref_type:
                        # Get the name of the called method
                        if child_field_name:
                            func_node = node.child_by_field_name(child_field_name)
                            if func_node and func_node.text.decode() in method_names:
                                method_name = func_node.text.decode()
                                references['method'][method_name].append(file_path)
                    
                    # Add children to stack with their parent
                    stack.extend((child, node) for child in node.children)
            except Exception as e:
                logger.error(f"在查找引用时处理文件 {file_path} 出错: {e}")
                continue
                
    return references

def write_class_data_to_csv(class_data, output_directory):
    class_data_path = os.path.join(output_directory, "class_data.csv")
    with open(class_data_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['file_path', 'class_name', 'constructor_declaration', 'method_declarations', 'source_code', 'references']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for data in class_data:
            references_str = ",".join(data['references'])
            data['references'] = references_str
            writer.writerow(data)

def write_method_data_to_csv(method_data, output_directory):
    method_data_path = os.path.join(output_directory, "method_data.csv")
    with open(method_data_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['file_path', 'class_name', 'name', 'doc_comment', 'source_code', 'references']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for data in method_data:
            references_str = ",".join(data['references'])
            data['references'] = references_str
            writer.writerow(data)

def create_output_directory(output_dir):
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    else:
        # 使用默认目录
        output_dir = os.path.join(os.getcwd(), "processed")
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

def process_codebase(codebase_name):
    """
    处理代码库并提取类和方法信息，作为预处理的主入口函数
    
    Args:
        code_path: 代码库的路径
        codebase_name: 代码库名称（可选）
        processed_dir: 输出处理数据的目录（可选）
        
    Returns:
        bool: 处理是否成功
    """
    if not codebase_name:
        return False
    
    try:
        # 加载文件
        processed_dir = get_codebase_path(codebase_name)["processed"]
        files = load_files(codebase_name)
        
        # 解析代码文件
        class_data, method_data, class_names, method_names = parse_code_files(files)

        # 查找引用
        references = find_references(files, class_names, method_names)

        # 将引用映射回类和方法数据
        class_data_dict = {cd['class_name']: cd for cd in class_data}
        method_data_dict = {(md['class_name'], md['name']): md for md in method_data}

        for class_name, refs in references['class'].items():
            if class_name in class_data_dict:
                class_data_dict[class_name]['references'] = refs

        for method_name, refs in references['method'].items():
            # 查找具有相同名称的所有方法（因为不同类中的方法可能具有相同的名称）
            for key in method_data_dict:
                if key[1] == method_name:
                    method_data_dict[key]['references'] = refs

        # 将字典转换回列表
        class_data = list(class_data_dict.values())
        method_data = list(method_data_dict.values())

        # 使用新的参数创建输出目录
        output_directory = create_output_directory(processed_dir)
        
        # 写入CSV文件
        write_class_data_to_csv(class_data, output_directory)
        write_method_data_to_csv(method_data, output_directory)
        
        logger.info(f"代码处理完成：找到 {len(class_data)} 个类和 {len(method_data)} 个方法")
        return True
    except Exception as e:
        logger.error(f"处理代码库时出错: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    pass