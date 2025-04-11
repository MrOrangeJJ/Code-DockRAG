#!/usr/bin/env node
// @ts-nocheck
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ListToolsRequestSchema, CallToolRequestSchema, ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import axios from "axios";
import dotenv from "dotenv";
import fs from "fs";
import path from "path";

// 加载环境变量
dotenv.config();

// 从环境变量中获取API基础URL
const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:30089";

// 定义参数接口
interface StandardSearchArgs {
  codebase_name: string;
  query: string;
  rerank?: boolean;
}

interface StrongSearchArgs {
  codebase_name: string;
  query: string;
}

interface GetFilesArgs {
  codebase_name: string;
  path?: string;
}

interface GetFileContentArgs {
  codebase_name: string;
  file_path: string;
}

interface BatchGetFileContentArgs {
  codebase_name: string;
  file_paths: string[];
}

interface FindReferencesArgs {
  codebase_name: string;
  file_path: string;
  symbol_name: string;
}

interface GetASTArgs {
  codebase_name: string;
}

interface SearchTextArgs {
  codebase_name: string;
  keyword: string;
}

// 参数验证函数
function isValidStandardSearchArgs(args: unknown): args is StandardSearchArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as StandardSearchArgs).codebase_name === "string" &&
    "query" in args &&
    typeof (args as StandardSearchArgs).query === "string" &&
    (
      !("rerank" in args) || 
      typeof (args as StandardSearchArgs).rerank === "boolean"
    )
  );
}

function isValidStrongSearchArgs(args: unknown): args is StrongSearchArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as StrongSearchArgs).codebase_name === "string" &&
    "query" in args &&
    typeof (args as StrongSearchArgs).query === "string"
  );
}

function isValidGetFilesArgs(args: unknown): args is GetFilesArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as GetFilesArgs).codebase_name === "string" &&
    (
      !("path" in args) || 
      typeof (args as GetFilesArgs).path === "string"
    )
  );
}

function isValidGetFileContentArgs(args: unknown): args is GetFileContentArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as GetFileContentArgs).codebase_name === "string" &&
    "file_path" in args &&
    typeof (args as GetFileContentArgs).file_path === "string"
  );
}

function isValidBatchGetFileContentArgs(args: unknown): args is BatchGetFileContentArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as BatchGetFileContentArgs).codebase_name === "string" &&
    "file_paths" in args &&
    Array.isArray((args as BatchGetFileContentArgs).file_paths) &&
    (args as BatchGetFileContentArgs).file_paths.every(path => typeof path === "string")
  );
}

function isValidFindReferencesArgs(args: unknown): args is FindReferencesArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as FindReferencesArgs).codebase_name === "string" &&
    "file_path" in args &&
    typeof (args as FindReferencesArgs).file_path === "string" &&
    "symbol_name" in args &&
    typeof (args as FindReferencesArgs).symbol_name === "string"
  );
}

function isValidGetASTArgs(args: unknown): args is GetASTArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as GetASTArgs).codebase_name === "string"
  );
}

function isValidSearchTextArgs(args: unknown): args is SearchTextArgs {
  return (
    typeof args === "object" &&
    args !== null &&
    "codebase_name" in args &&
    typeof (args as SearchTextArgs).codebase_name === "string" &&
    "keyword" in args &&
    typeof (args as SearchTextArgs).keyword === "string"
  );
}

// 检查代码库是否存在且已索引的辅助函数
async function checkCodebaseExists(codebase_name: string): Promise<boolean> {
  try {
    const response = await axios.get(`${API_BASE_URL}/codebases/indexed`);
    const codebases = response.data;
    return codebases.some(codebase => 
      codebase.name === codebase_name && 
      codebase.indexed === true
    );
  } catch (error) {
    console.error("Error checking if codebase exists:", error);
    return false;
  }
}

// MCP服务器类
class CodeDockServer {
  private server: Server;

  constructor() {
    this.server = new Server(
      { name: "code-dock-mcp", version: "1.0.0" },
      { capabilities: { tools: {} } }
    );

    this.setupHandlers();
    this.setupErrorHandling();
  }

  private setupErrorHandling(): void {
    this.server.onerror = (error: Error) => {
      console.error("[MCP Error]", error);
    };

    process.on("SIGINT", async () => {
      await this.server.close();
      process.exit(0);
    });
  }

  private setupHandlers(): void {
    // 列出可用工具
    this.server.setRequestHandler(
      ListToolsRequestSchema,
      async () => ({
        tools: [
          {
            name: "list_codebases",
            description: "Lists all available indexed codebases with their descriptions. This tool is the starting point for code analysis and must be called first to identify available codebases. Results include codebase names and brief descriptions of their purpose and structure. Always use this tool before any other codebase-related operations to ensure the target codebase exists and is properly indexed. The returned information will help you select the appropriate codebase for your analysis.",
            inputSchema: {
              type: "object",
              properties: {
                random_string: {
                  type: "string",
                  description: "Dummy parameter for no-parameter tools"
                }
              },
              required: ["random_string"]
            }
          },
          {
            name: "standard_search",
            description: "Performs a RAG-based (Retrieval-Augmented Generation) semantic search within the specified codebase. This tool understands the meaning behind your query rather than just matching keywords, making it excellent for finding code related to concepts, features, or specific functionality. Results include matching file paths, relevant code snippets, and matched functions or classes.\n\nUnlike grep searches, this tool understands programming concepts and can find semantically related code even when exact terms differ. If initial results aren't satisfactory, try rephrasing your query or using more specific programming terminology.\n\nThe optional rerank parameter can improve result relevance by applying additional ranking algorithms. While faster than strong_search, it may be less precise for complex queries.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase to search within. Use list_codebases to find available codebases."
                },
                query: {
                  type: "string",
                  description: "The search query text expressing what you're looking for in natural language"
                },
                rerank: {
                  type: "boolean",
                  description: "Whether to apply additional ranking to improve result relevance. Default is false."
                }
              },
              required: ["codebase_name", "query"]
            }
          },
          {
            name: "strong_search",
            description: "Performs an advanced LLM-powered intelligent search of the codebase with deeper code understanding capabilities. This tool excels at handling complex, abstract, or high-level queries about code architecture, implementation logic, or functionality patterns.\n\nCompared to standard_search, this tool provides more precise and contextually relevant results by leveraging a larger language model to truly understand both your query and the codebase structure. It can recognize programming patterns, architectural concepts, and implementation strategies beyond simple keyword matching.\n\nResults often include code analysis, relevant file paths, code snippets, and explanations about how they relate to your query. If one search doesn't yield satisfactory results, try multiple calls with refined queries. While processing may take longer than standard_search, the quality and relevance of results are significantly higher, especially for complex questions about code functionality or architecture.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase to search within. Use list_codebases to find available codebases."
                },
                query: {
                  type: "string",
                  description: "The complex or high-level search query in natural language"
                }
              },
              required: ["codebase_name", "query"]
            }
          },
          {
            name: "get_files",
            description: "Lists files and directories at the specified path in the codebase. This navigation tool helps you explore the codebase structure systematically, starting from the root directory and drilling down into specific project areas. Results include file names, paths, types (file or directory), and modification dates.\n\nUse this tool to discover available files before requesting their contents, or to navigate through project directories step by step. It works well in combination with get_ast to understand both the file organization and code structure within those files.\n\nIf you provide a non-existent path, the tool will suggest using get_ast to view the correct file structure. For repositories with many files, start with the root directory and navigate progressively through subdirectories to maintain context and avoid information overload.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase to explore. Use list_codebases to find available codebases."
                },
                path: {
                  type: "string",
                  description: "Optional path to list contents from. If not provided, lists content from the root directory."
                }
              },
              required: ["codebase_name"]
            }
          },
          {
            name: "get_file_content",
            description: "Retrieves the complete content of a specific file from the codebase. This tool is essential for detailed code analysis, allowing you to examine source code, configuration files, documentation, or any text-based file in the repository.\n\nBefore using this tool, first identify the correct file path using get_files or get_ast. The file_path parameter should be relative to the codebase root directory (e.g., \"src/main/java/com/example/MyClass.java\").\n\nThis tool is ideal when you need to analyze a single file in depth, understand specific implementations, or examine how certain features are coded. If the requested file doesn't exist, the tool will suggest using get_ast to find the correct file paths. For analyzing multiple related files simultaneously, consider using batch_get_file_content instead for better efficiency.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase containing the file. Use list_codebases to find available codebases."
                },
                file_path: {
                  type: "string",
                  description: "The relative path to the file from the codebase root. Use get_files or get_ast to find correct paths."
                }
              },
              required: ["codebase_name", "file_path"]
            }
          },
          {
            name: "batch_get_file_content",
            description: "Retrieves the contents of multiple files in a single operation. This efficient tool is superior to making multiple individual file requests when you need to analyze several related files together, such as tracing function calls across files, understanding class hierarchies, or examining a complete feature implementation.\n\nProvide an array of file paths (relative to the codebase root) to retrieve all contents simultaneously. The response returns a mapping object where keys are file paths and values are file contents. Even if some files don't exist, the tool will return contents for all valid paths along with error messages for invalid ones.\n\nUse get_files or get_ast first to identify the correct file paths. This tool is particularly valuable when analyzing related code that spans multiple files, following implementation patterns, or understanding cross-file dependencies in the codebase.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase containing the files. Use list_codebases to find available codebases."
                },
                file_paths: {
                  type: "array",
                  items: {
                    type: "string"
                  },
                  description: "Array of file paths (relative to codebase root) to retrieve. Use get_files or get_ast to find correct paths."
                }
              },
              required: ["codebase_name", "file_paths"]
            }
          },
          {
            name: "find_references",
            description: "Locates all references to a specific symbol (function, class, variable, etc.) throughout the codebase, similar to the \"Go to References\" functionality in IDEs. This powerful tool helps you understand how and where a particular code element is used, which is essential for assessing the impact of potential changes, tracing execution flows, or understanding code dependencies.\n\nBefore using this tool, first identify the target symbol by exploring the codebase with get_ast (to see classes and functions) or get_file_content (to examine specific files). The tool requires:\n- file_path: The file containing the symbol definition\n- symbol_name: The exact name of the function, class, or variable to find references for\n\nResults include all reference locations with file paths, line numbers, and code snippets showing usage context. This tool is invaluable when you need to understand a symbol's usage patterns, evaluate refactoring impacts, or track down specific code usages across the project.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase to search within. Use list_codebases to find available codebases."
                },
                file_path: {
                  type: "string",
                  description: "The file path containing the symbol definition. Use get_files or get_ast to find correct paths."
                },
                symbol_name: {
                  type: "string",
                  description: "The exact name of the symbol (function, class, variable) to find references for."
                }
              },
              required: ["codebase_name", "file_path", "symbol_name"]
            }
          },
          {
            name: "get_ast",
            description: "Retrieves the Abstract Syntax Tree (AST) representation of the codebase, providing a comprehensive structural view of the entire project. This high-level overview includes all files, classes, methods, and their relationships, making it an excellent starting point for understanding large or unfamiliar codebases.\n\nThe AST provides crucial information for other tools:\n- Accurate file paths needed for get_file_content and other file operations\n- Complete list of classes and their methods for find_references\n- Overall project structure to guide your exploration\n\nUse this tool early in your analysis to identify key components, understand code organization, and discover important classes or functions without examining individual files. It's especially valuable for navigating large projects or when you need to quickly identify structural elements to focus on.\n\nThe returned structure can also help verify file paths when other tools report \"file not found\" errors, providing the correct paths to use in subsequent requests.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase to analyze. Use list_codebases to find available codebases."
                }
              },
              required: ["codebase_name"]
            }
          },
          {
            name: "search_text",
            description: "Searches for a specific keyword or text pattern within the codebase files. This tool performs a basic text search (similar to grep) across all files in the codebase, returning a list of files containing exact matches of the specified keyword. Use this tool when you need to find all occurrences of specific terms, function names, variable names, or error messages. Results include the matched file paths and names, making it easy to identify where certain text appears in the codebase. This is particularly useful for locating specific implementations, error handling code, or usage of particular constants or identifiers.",
            inputSchema: {
              type: "object",
              properties: {
                codebase_name: {
                  type: "string",
                  description: "The name of the codebase to search within. Use list_codebases to find available codebases."
                },
                keyword: {
                  type: "string",
                  description: "The exact text or keyword to search for in the codebase files."
                }
              },
              required: ["codebase_name", "keyword"]
            }
          }
        ]
      })
    );

    // 处理工具调用
    this.server.setRequestHandler(
      CallToolRequestSchema,
      async (request) => {
        switch (request.params.name) {
          case "list_codebases": {
            try {
              // 获取已索引的代码库列表
              const url = `${API_BASE_URL}/codebases/indexed`;
              const response = await axios.get(url);
              
              // 提取需要的信息并处理
              const simplifiedList = response.data.map(codebase => ({
                name: codebase.name,
                description: "Loading description..." // 先设置一个临时描述
              }));
              
              // 为每个代码库获取描述
              for (let i = 0; i < simplifiedList.length; i++) {
                try {
                  const descUrl = `${API_BASE_URL}/codebases/${simplifiedList[i].name}/description`;
                  const descResponse = await axios.get(descUrl);
                  simplifiedList[i].description = descResponse.data;
                } catch (error) {
                  console.error(`Error getting description for ${simplifiedList[i].name}:`, error);
                  simplifiedList[i].description = "No description available";
                }
              }
              
              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(simplifiedList, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error listing codebases:", error);
              return {
                content: [{
                  type: "text",
                  text: `Failed to list codebases: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "standard_search": {
            if (!isValidStandardSearchArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid standard_search arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              const url = `${API_BASE_URL}/search`;
              const response = await axios.post(url, {
                codebase_name: request.params.arguments.codebase_name,
                query: request.params.arguments.query,
                rerank: request.params.arguments.rerank || false
              });

              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error performing standard search:", error);
              if (error.response && error.response.status === 404) {
                return {
                  content: [{
                    type: "text",
                    text: `该codebase不存在或未索引，请运行list_codebases查看已经存在的codebase_name`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to perform search: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "strong_search": {
            if (!isValidStrongSearchArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid strong_search arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              const url = `${API_BASE_URL}/strong_search`;
              const response = await axios.post(url, {
                codebase_name: request.params.arguments.codebase_name,
                query: request.params.arguments.query
              });

              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error performing strong search:", error);
              if (error.response && error.response.status === 404) {
                return {
                  content: [{
                    type: "text",
                    text: `该codebase不存在或未索引，请运行list_codebases查看已经存在的codebase_name`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to perform strong search: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "get_files": {
            if (!isValidGetFilesArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid get_files arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              let url = `${API_BASE_URL}/codebases/${request.params.arguments.codebase_name}/files`;
              if (request.params.arguments.path) {
                url += `?path=${encodeURIComponent(request.params.arguments.path)}`;
              }

              const response = await axios.get(url);
              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error listing files:", error);
              if (error.response && error.response.status === 404) {
                if (error.response.data && error.response.data.detail && error.response.data.detail.includes("不存在")) {
                  return {
                    content: [{
                      type: "text",
                      text: `查找的路径不存在，请调用列出ast tree工具查看项目的正确文件目录`
                    }],
                    isError: true
                  };
                }
                return {
                  content: [{
                    type: "text",
                    text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                  }],
                  isError: true
                };
              } else if (error.response && error.response.status === 400) {
                return {
                  content: [{
                    type: "text",
                    text: `查找的路径无效，请调用列出ast tree工具查看项目的正确文件目录`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to list files: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "get_file_content": {
            if (!isValidGetFileContentArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid get_file_content arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              const url = `${API_BASE_URL}/codebases/${request.params.arguments.codebase_name}/files/${encodeURIComponent(request.params.arguments.file_path)}`;
              const response = await axios.get(url);
              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error getting file content:", error);
              if (error.response && error.response.status === 404) {
                return {
                  content: [{
                    type: "text",
                    text: `查找的文件路径不存在，请调用列出ast tree工具查看项目的正确文件目录`
                  }],
                  isError: true
                };
              } else if (error.response && error.response.status === 400) {
                return {
                  content: [{
                    type: "text",
                    text: `查找的文件路径无效，请调用列出ast tree工具查看项目的正确文件目录`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to get file content: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "batch_get_file_content": {
            if (!isValidBatchGetFileContentArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid batch_get_file_content arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              const url = `${API_BASE_URL}/codebases/${request.params.arguments.codebase_name}/files/batch`;
              const response = await axios.post(url, {
                file_paths: request.params.arguments.file_paths
              });

              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error batch getting file content:", error);
              if (error.response && error.response.status === 404) {
                return {
                  content: [{
                    type: "text",
                    text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to batch get file content: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "find_references": {
            if (!isValidFindReferencesArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid find_references arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              const url = `${API_BASE_URL}/codebases/${request.params.arguments.codebase_name}/references/find`;
              const response = await axios.post(url, {
                file_path: request.params.arguments.file_path,
                symbol_name: request.params.arguments.symbol_name
              });

              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error finding references:", error);
              if (error.response && error.response.status === 404) {
                if (error.response.data && error.response.data.detail && error.response.data.detail.includes("不存在")) {
                  return {
                    content: [{
                      type: "text",
                      text: `查找的文件路径不存在，请调用列出ast tree工具查看项目的正确文件目录`
                    }],
                    isError: true
                  };
                }
                return {
                  content: [{
                    type: "text",
                    text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to find references: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "get_ast": {
            if (!isValidGetASTArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid get_ast arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              const url = `${API_BASE_URL}/codebases/${request.params.arguments.codebase_name}/ast`;
              const response = await axios.get(url);
              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error getting AST:", error);
              if (error.response && error.response.status === 404) {
                return {
                  content: [{
                    type: "text",
                    text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to get AST: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          case "search_text": {
            if (!isValidSearchTextArgs(request.params.arguments)) {
              throw new McpError(
                ErrorCode.InvalidParams,
                "Invalid search_text arguments"
              );
            }

            // 检查代码库是否存在且已索引
            const codebaseExists = await checkCodebaseExists(request.params.arguments.codebase_name);
            if (!codebaseExists) {
              return {
                content: [{
                  type: "text",
                  text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                }],
                isError: true
              };
            }

            try {
              const url = `${API_BASE_URL}/codebases/${request.params.arguments.codebase_name}/search/text?keyword=${encodeURIComponent(request.params.arguments.keyword)}`;
              const response = await axios.get(url);
              return {
                content: [{
                  type: "text",
                  text: JSON.stringify(response.data, null, 2)
                }]
              };
            } catch (error) {
              console.error("Error searching text:", error);
              if (error.response && error.response.status === 404) {
                return {
                  content: [{
                    type: "text",
                    text: `该codebase不存在，请运行list_codebases查看已经存在的codebase_name`
                  }],
                  isError: true
                };
              } else if (error.response && error.response.status === 400) {
                return {
                  content: [{
                    type: "text",
                    text: `搜索关键词不能为空`
                  }],
                  isError: true
                };
              }
              return {
                content: [{
                  type: "text",
                  text: `Failed to search text: ${error instanceof Error ? error.message : String(error)}`
                }],
                isError: true
              };
            }
            break;
          }

          default:
            throw new McpError(
              ErrorCode.InvalidParams,
              `Unknown tool: ${request.params.name}`
            );
        }
      }
    );
  }

  async run(): Promise<void> {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
  }
}

// 启动服务器
const server = new CodeDockServer();
server.run().catch(error => {
  console.error("Server failed:", error);
  process.exit(1);
}); 