# Code Dock MCP Tools

这是一个用于与Code Dock Search API交互的MCP(Model Context Protocol)工具集。它允许大型语言模型(LLM)通过[Model Context Protocol](https://modelcontextprotocol.io/)直接访问代码库管理、搜索和分析功能。

## 功能

此MCP工具集提供以下功能：

- **代码库管理**：列出、上传、索引和删除代码库
- **代码搜索**：标准RAG搜索和智能LLM支持的强效搜索
- **文件管理**：列出文件、获取文件内容、上传和删除文件
- **代码分析**：查找符号引用

## 安装

```bash
# 克隆仓库
git clone [repository-url]
cd code_dock_mcp

# 安装依赖
npm install

# 复制环境变量示例并编辑
cp .env.example .env
```

编辑`.env`文件，设置API基础URL：

```
API_BASE_URL=http://localhost:30089  # 替换为实际的API地址
```

## 构建

```bash
npm run build
```

## 使用

此MCP工具可以与支持Model Context Protocol的应用程序一起使用，如Claude Desktop App。

### 在Claude Desktop App中设置

1. 打开Claude Desktop App
2. 转到设置 > MCP服务器
3. 添加新服务器
4. 设置以下参数：
   - 命令: `node`
   - 参数: 添加两个参数: `[完整路径到]/code_dock_mcp/dist/index.js`

例如：
```json
{
  "codedock": {
    "command": "node",
    "args": ["/Users/yourname/code_dock_mcp/dist/index.js"]
  }
}
```

## 可用工具

本MCP服务器提供以下工具：

1. **list_codebases** - 列出所有代码库
2. **standard_search** - 执行基础的RAG搜索
3. **strong_search** - 执行高级的LLM辅助搜索
4. **get_files** - 列出代码库中的文件
5. **get_file_content** - 获取文件内容
6. **batch_get_file_content** - 批量获取多个文件的内容
7. **upload_codebase** - 上传新代码库
8. **index_codebase** - 索引代码库
9. **delete_codebase** - 删除代码库
10. **upload_file** - 上传单个文件
11. **delete_file** - 删除文件
12. **find_references** - 查找代码引用
13. **get_websocket_client_id** - 获取WebSocket客户端ID
14. **websocket_strong_search** - 关于WebSocket强力搜索的信息

## 示例查询

以下是一些可以向Claude提出的示例查询：

- "列出所有已索引的代码库"
- "在my-project代码库中搜索登录功能的实现"
- "获取my-project代码库中的src/main.py文件内容"
- "在my-project代码库中查找User类的所有引用"

## 需求

- Node.js 18+
- 连接到运行中的Code Dock Search API服务

## 许可证

MIT 