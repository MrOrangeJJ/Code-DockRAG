from abc import ABC
from tree_sitter import Language, Parser
from tree_sitter_languages import get_language, get_parser
from enum import Enum
import logging
import os
import json
from collections import defaultdict
from typing import Dict, Any, Optional

# 导入共享的常量
from .utils import(
    read_file_safely, 
    get_language_from_extension, 
    get_codebase_path, 
    get_language_from_extension, 
    read_file_safely, 
    load_config_file
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class LanguageEnum(Enum):
    JAVA = "java"
    PYTHON = "python"
    RUST = "rust"
    JAVASCRIPT = "javascript"
    UNKNOWN = "unknown"

LANGUAGE_QUERIES = {
    LanguageEnum.JAVA: {
        'class_query': """
            (class_declaration
                name: (identifier) @class.name)
        """,
        'method_query': """
            [
                (method_declaration
                    name: (identifier) @method.name)
                (constructor_declaration
                    name: (identifier) @method.name)
            ]
        """,
        'doc_query': """
            ((block_comment) @comment)
        """
    },
    LanguageEnum.PYTHON: {
        'class_query': """
            (class_definition
                name: (identifier) @class.name)
        """,
        'method_query': """
            (function_definition
                name: (identifier) @function.name)
        """,
        'doc_query': """
            (expression_statement
                (string) @comment)
        """
    },
    LanguageEnum.RUST: {
        'class_query': """
            (struct_item
                name: (type_identifier) @class.name)
        """,
        'method_query': """
            (function_item
                name: (identifier) @function.name)
        """,
        'doc_query': """
            [
                (line_comment) @comment
                (block_comment) @comment
            ]
        """
    },
    LanguageEnum.JAVASCRIPT: {
        'class_query': """
            (class_declaration
                name: (identifier) @class.name)
        """,
        'method_query': """
            (method_definition
                name: (property_identifier) @method.name)
        """,
        'doc_query': """
            ((comment) @comment)
        """
    },
    # Add other languages as needed
}

class TreesitterMethodNode:
    def __init__(
        self,
        name: str,
        doc_comment: str,
        method_source_code: str,
        node,
        class_name: str = None
    ):
        self.name = name
        self.doc_comment = doc_comment
        self.method_source_code = method_source_code
        self.node = node
        self.class_name = class_name

class TreesitterClassNode:
    def __init__(
        self,
        name: str,
        method_declarations: list,
        node,
    ):
        self.name = name
        self.source_code = node.text.decode()
        self.method_declarations = method_declarations
        self.node = node

class Treesitter(ABC):
    def __init__(self, language: LanguageEnum):
        self.language_enum = language
        self.parser = get_parser(language.value)
        self.language_obj = get_language(language.value)
        self.query_config = LANGUAGE_QUERIES.get(language)
        if not self.query_config:
            raise ValueError(f"Unsupported language: {language}")

        # Corrected query instantiation
        self.class_query = self.language_obj.query(self.query_config['class_query'])
        self.method_query = self.language_obj.query(self.query_config['method_query'])
        self.doc_query = self.language_obj.query(self.query_config['doc_query'])

    @staticmethod
    def create_treesitter(language: LanguageEnum) -> "Treesitter":
        return Treesitter(language)

    def parse(self, file_bytes: bytes) -> tuple[list[TreesitterClassNode], list[TreesitterMethodNode]]:
        tree = self.parser.parse(file_bytes)
        root_node = tree.root_node

        class_results = []
        method_results = []

        class_name_by_node = {}
        class_captures = self.class_query.captures(root_node)
        class_nodes = []
        for node, capture_name in class_captures:
            if capture_name == 'class.name':
                class_name = node.text.decode()
                class_node = node.parent
                class_name_by_node[class_node.id] = class_name
                method_declarations = self._extract_methods_in_class(class_node)
                class_results.append(TreesitterClassNode(class_name, method_declarations, class_node))
                class_nodes.append(class_node)

        method_captures = self.method_query.captures(root_node)
        for node, capture_name in method_captures:
            if capture_name in ['method.name', 'function.name']:
                method_name = node.text.decode()
                method_node = node.parent
                method_source_code = method_node.text.decode()
                doc_comment = self._extract_doc_comment(method_node)
                parent_class_name = None
                for class_node in class_nodes:
                    if self._is_descendant_of(method_node, class_node):
                        parent_class_name = class_name_by_node[class_node.id]
                        break
                method_results.append(TreesitterMethodNode(
                    name=method_name,
                    doc_comment=doc_comment,
                    method_source_code=method_source_code,
                    node=method_node,
                    class_name=parent_class_name
                ))

        return class_results, method_results

    def _extract_methods_in_class(self, class_node):
        method_declarations = []
        # Apply method_query to the class_node
        method_captures = self.method_query.captures(class_node)
        for node, capture_name in method_captures:
            if capture_name in ['method.name', 'function.name']:
                method_declaration = node.parent.text.decode()
                method_declarations.append(method_declaration)
        return method_declarations

    def _extract_doc_comment(self, node):
        # Search for doc comments preceding the node
        doc_comment = ''
        current_node = node.prev_sibling
        while current_node:
            captures = self.doc_query.captures(current_node)
            if captures:
                for cap_node, cap_name in captures:
                    if cap_name == 'comment':
                        doc_comment = cap_node.text.decode() + '\n' + doc_comment
            elif current_node.type not in ['comment', 'block_comment', 'line_comment', 'expression_statement']:
                # Stop if we reach a node that's not a comment
                break
            current_node = current_node.prev_sibling
        return doc_comment.strip()

    def _is_descendant_of(self, node, ancestor):
        # Check if 'node' is a descendant of 'ancestor'
        current = node.parent
        while current:
            if current == ancestor:
                return True
            current = current.parent
        return False


def generate_codebase_ast_structure(codebase_name: str):
    """
    为整个代码库生成AST树结构摘要，直接实现不依赖generate_project_structure
    
    Args:
        codebase_path: 代码库根目录路径
        
    Returns:
        dict: 表示代码库结构的字典，包含文件和主要语法单元
    """

    codebase_path = get_codebase_path(codebase_name)
    code_path = codebase_path["code"]

    processed_path = codebase_path["processed"]
    structure_path = os.path.join(processed_path, "ast_structure.json")
    if os.path.exists(structure_path):
        ast_structure = load_project_structure(structure_path)
        return ast_structure

    
    # 初始化结构
    ast_structure = {
        "name": os.path.basename(code_path),
        "path": code_path,
        "file_count": 0,
        "languages": {},
        "files": []
    }
    
    # 语言统计计数器
    language_counter = {}
    file_count = 0
    
    # 遍历代码库中的文件
    for root, dirs, files in os.walk(code_path):
        # 跳过黑名单目录
        dirs[:] = [d for d in dirs if d not in load_config_file(codebase_name, "ignore_dirs")]
        
        for file in files:
            file_ext = os.path.splitext(file)[1]
            # 过滤出需要处理的文件
            if file_ext in load_config_file(codebase_name, "whitelist_files") or any(wf in file for wf in load_config_file(codebase_name, "whitelist_files") if not wf.startswith('.')):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, code_path)
                
                # 获取语言信息
                language = None
                language_enum = get_language_from_extension(file_ext)
                if language_enum:
                    language = language_enum.value
                    # 更新语言统计
                    if language in language_counter:
                        language_counter[language] += 1
                    else:
                        language_counter[language] = 1
                
                # 获取文件大小
                try:
                    file_size = os.path.getsize(file_path)
                except:
                    file_size = 0
                
                # 提取文件中的类和方法(如果有语言支持)
                classes = []
                methods = []
                
                if language_enum:
                    try:
                        parser = Treesitter.create_treesitter(language_enum)
                        content = read_file_safely(file_path)
                        if content:
                            file_bytes = content.encode('utf-8')
                            class_nodes, method_nodes = parser.parse(file_bytes)
                            
                            # 处理类
                            for node in class_nodes:
                                class_info = {
                                    "name": node.name,
                                    "methods": []
                                }
                                # 可以在这里进一步提取类的更多信息
                                classes.append(class_info)
                            
                            # 处理方法
                            for node in method_nodes:
                                method_info = {
                                    "name": node.name,
                                    "class_name": node.class_name
                                }
                                # 可以在这里进一步提取方法的更多信息
                                methods.append(method_info)
                    except Exception as e:
                        logging.warning(f"处理文件AST时出错: {rel_path} - {e}")
                
                # 构建文件信息
                file_info = {
                    "path": rel_path,
                    "language": language or "unknown",
                    "size": file_size,
                    "classes": classes,
                    "methods": methods
                }
                
                ast_structure["files"].append(file_info)
                file_count += 1
    
    # 更新总体统计
    ast_structure["file_count"] = file_count
    ast_structure["languages"] = language_counter

    success = save_project_structure(ast_structure, structure_path)

    return ast_structure



def dict_to_readable_tree(codebase_name: str) -> str:
    """
    将项目结构字典转换为人类和LLM友好的文本树
    
    Args:
        structure_dict: 项目结构字典
        
    Returns:
        str: 格式化的文本树
    """

    structure_dict = generate_project_structure(codebase_name)
    result = []
    
    # 添加项目基本信息
    root_path = structure_dict.get("root_path", "未知路径")
    file_count = structure_dict.get("file_count", 0)
    languages = structure_dict.get("languages", {})
    
    result.append(f"项目根目录: {root_path}")
    result.append(f"文件总数: {file_count}")
    
    # 添加语言统计
    if languages:
        result.append("语言统计:")
        for lang, count in languages.items():
            result.append(f"  - {lang}: {count}个文件")
    
    # 递归构建文件树
    tree = structure_dict.get("tree", {})
    result.append("\n文件结构:")
    
    def _build_tree_text(node, prefix="", is_last=True, path=""):
        lines = []
        
        # 生成当前节点的行
        if is_last:
            branch = "└── "
            new_prefix = prefix + "    "
        else:
            branch = "├── "
            new_prefix = prefix + "│   "
        
        # 如果是文件
        if node.get("type") == "file":
            file_name = path.split("/")[-1]
            language = node.get("language", "")
            lang_tag = f" [{language}]" if language else ""
            
            # 检查是否有类和方法
            classes = node.get("classes", [])
            methods = node.get("methods", [])
            has_content = classes or methods
            
            line = f"{prefix}{branch}{file_name}{lang_tag}"
            lines.append(line)
            
            # 添加类和方法信息(如果有)
            if has_content:
                for cls in classes:
                    class_name = cls.get("name", "未命名类")
                    cls_methods = cls.get("methods", [])
                    
                    if is_last:
                        cls_prefix = prefix + "    "
                    else:
                        cls_prefix = prefix + "│   "
                        
                    lines.append(f"{cls_prefix}└── class: {class_name}")
                    
                    # 添加类的方法
                    if cls_methods:
                        method_prefix = cls_prefix + "    "
                        for idx, method in enumerate(cls_methods):
                            method_name = method.get("name", "未命名方法")
                            lines.append(f"{method_prefix}└── {method_name}()")
                
                # 添加独立方法
                if methods and not is_last:
                    method_prefix = prefix + "│   "
                else:
                    method_prefix = prefix + "    "
                    
                for idx, method in enumerate(methods):
                    method_name = method.get("name", "未命名方法")
                    lines.append(f"{method_prefix}└── {method_name}()")
                    
        # 如果是目录
        else:
            dir_name = path.split("/")[-1] if path else "/"
            line = f"{prefix}{branch}{dir_name}/"
            lines.append(line)
            
            # 处理子节点
            children = node.get("children", {})
            items = list(children.items())
            
            for i, (child_name, child_node) in enumerate(items):
                is_child_last = i == len(items) - 1
                new_path = f"{path}/{child_name}" if path else child_name
                child_lines = _build_tree_text(
                    child_node, 
                    new_prefix, 
                    is_child_last,
                    new_path
                )
                lines.extend(child_lines)
                
        return lines
    
    # 处理根目录
    root_items = list(tree.items())
    for i, (name, node) in enumerate(root_items):
        is_last = i == len(root_items) - 1
        path_lines = _build_tree_text(node, "", is_last, name)
        result.extend(path_lines)
    
    return "\n".join(result)

def build_tree_from_ast(ast_structure: Dict[str, Any]) -> Dict[str, Any]:
    """
    从AST结构构建树形结构
    
    Args:
        ast_structure: AST结构信息
        
    Returns:
        树形结构
    """
    files = ast_structure.get("files", [])
    tree = {}
    
    for file_info in files:
        path = file_info.get("path", "")
        if not path:
            continue
            
        # 将路径分割成目录和文件名
        parts = path.split("/")
        current = tree
        
        # 构建目录结构
        for i, part in enumerate(parts):
            if i == len(parts) - 1:  # 最后一部分是文件名
                # 添加文件及其元数据
                current[part] = {
                    "type": "file",
                    "language": file_info.get("language", "unknown"),
                    "size": file_info.get("size", 0),
                    "classes": file_info.get("classes", []),
                    "methods": file_info.get("methods", [])
                }
            else:
                # 构建或访问目录
                if part not in current:
                    current[part] = {"type": "directory", "children": {}}
                current = current[part]["children"]
    
    return tree

def generate_project_structure(codebase_name: str) -> Dict[str, Any]:
    """
    生成项目结构信息，包含文件tree和AST元数据
    
    Args:
        codebase_name: 代码库名称
        
    Returns:
        项目结构信息的字典
    """

    codebase_path = get_codebase_path(codebase_name)
    code_path = codebase_path["code"]

    processed_path = codebase_path["processed"]
    structure_path = os.path.join(processed_path, "project_structure.json")
    if os.path.exists(structure_path):
        tree_structure = load_project_structure(structure_path)
        return tree_structure


    # 生成代码库AST结构
    ast_structure = generate_codebase_ast_structure(codebase_name)
    # 从AST结构构建树形结构
    tree_structure = {
        "root_path": code_path,
        "file_count": ast_structure.get("file_count", 0),
        "languages": ast_structure.get("languages", {}),
        "tree": build_tree_from_ast(ast_structure)
    }
    
    success = save_project_structure(tree_structure, structure_path)
    
    return tree_structure


def save_project_structure(structure_dict: Dict[str, Any], save_path: str) -> bool:
    """
    将项目结构保存到文件中
    
    Args:
        structure_dict: 项目结构字典
        save_path: 保存路径
        
    Returns:
        bool: 保存是否成功
    """
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(structure_dict, f, ensure_ascii=False, indent=2)
        logging.info(f"项目结构已保存到: {save_path}")
        return True
    except Exception as e:
        logging.error(f"保存项目结构时出错: {str(e)}")
        return False

def load_project_structure(load_path: str) -> Optional[Dict[str, Any]]:
    """
    从文件加载项目结构
    
    Args:
        load_path: 加载路径
        
    Returns:
        Optional[Dict[str, Any]]: 项目结构字典，失败时返回None
    """
    try:
        if not os.path.exists(load_path):
            logging.warning(f"项目结构文件不存在: {load_path}")
            return None
            
        with open(load_path, 'r', encoding='utf-8') as f:
            structure = json.load(f)
        logging.info(f"已从 {load_path} 加载项目结构")
        return structure
    except Exception as e:
        logging.error(f"加载项目结构时出错: {str(e)}")
        return None

def generate_formatted_structure(codebase_name: str) -> str:
    """
    生成格式化的代码库结构文本，显示文件、类和方法的层次结构
    
    Args:
        codebase_name: 代码库名称
        
    Returns:
        str: 格式化的结构文本
    """
    # 获取项目结构
    ast_structure = generate_codebase_ast_structure(codebase_name)
    
    # 准备输出文本
    result = []
    
    # 获取所有文件
    files = ast_structure.get("files", [])
    
    # 按文件路径对文件排序
    sorted_files = sorted(files, key=lambda x: x.get("path", ""))
    
    # 处理每个文件
    for file_info in sorted_files:
        file_path = file_info.get("path", "未知路径")
        classes = file_info.get("classes", [])
        methods = file_info.get("methods", [])
        
        # 添加分隔线和文件路径
        result.append("-"*70)
        result.append(f"{file_path}")
        
        # 添加类和它们的方法
        for cls in classes:
            class_name = cls.get("name", "未命名类")
            result.append(f"\t{class_name}")
            
            # 如果有指定类的方法列表，则使用它
            cls_methods = cls.get("methods", [])
            if isinstance(cls_methods, list) and len(cls_methods) > 0:
                # 尝试从方法数组中获取名称
                for method in cls_methods:
                    if isinstance(method, dict) and "name" in method:
                        method_name = method.get("name", "未命名方法")
                        result.append(f"\t\t{method_name}")
                    elif isinstance(method, str):
                        # 如果是字符串，尝试提取方法名称
                        # 这里使用简单方法：假设方法定义以 "def" 开头
                        method_name = method.strip().split("def ", 1)[-1].split("(")[0].strip()
                        result.append(f"\t\t{method_name}")
        
        # 添加文件级别的方法（不属于任何类的方法）
        for method in methods:
            # 只添加不属于任何类的方法
            if not method.get("class_name"):
                method_name = method.get("name", "未命名方法")
                result.append(f"\t{method_name}()")
    
    # 添加最后的分隔线
    if result:
        result.append("-"*70)
    
    return "\n".join(result)


if __name__ == "__main__":
    print(generate_formatted_structure("Test"))