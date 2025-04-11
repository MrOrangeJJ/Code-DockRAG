# Code Dock - Intelligent Code Search and Exploration Platform

<div align="right">
  <a href="#code-dock---intelligent-code-search-and-exploration-platform">English</a> | 
  <a href="#code-dock---智能代码搜索与探索平台">中文</a>
</div>

Code Dock is a comprehensive solution for code search, exploration, and analysis, enabling seamless interaction with codebases through AI-powered search capabilities.


## 📚 Documentation

For detailed documentation, please refer to:

- [Installation Guide](docs/INSTALLATION.md) - Detailed setup instructions
- [User Guide](docs/USER_GUIDE.md) - How to use the platform
- [API Reference](docs/API_REFERENCE.md) - API endpoint documentation
- [MCP Tools Guide](docs/MCP_GUIDE.md) - LLM integration via MCP
- [Docker Deployment](docs/DOCKER_DEPLOYMENT.md) - Containerized deployment
- [Development Guide](docs/DEVELOPMENT.md) - Contributing to Code Dock

## 🌟 Features

- **Multiple Search Modes**
  - Standard semantic search (RAG-based)
  - Advanced AI-powered search with LLM assistance
  - Text-based keyword search
  
- **Code Understanding**
  - Abstract Syntax Tree (AST) visualization
  - Symbol reference tracking
  - File and directory exploration
  
- **Rich UI Experience**
  - Interactive web interface
  - Real-time search with WebSocket feedback
  - Visual code structure exploration
  
- **LLM Integration**
  - MCP (Model Context Protocol) tools for direct LLM interaction
  - Support for Claude, Qwen Plus, GPT-4 and other language models
  - Agent-based intelligent exploration

## 🏗️ Architecture

The system consists of three main components:

1. **Backend (Python)**
   - Core search and indexing engine powered by FastAPI
   - Tree-sitter powered code parsing for multiple languages
   - LanceDB vector database for embeddings storage
   - OpenAI and VoyageAI compatible embedding generation

2. **Web Frontend**
   - Modern HTML/CSS/JavaScript interface
   - WebSocket-based real-time communication
   - Interactive visualization components

3. **MCP Integration**
   - Tools for seamless LLM integration
   - Support for Claude Desktop App
   - Rich toolset for codebase exploration

## 🚀 Quick Start

```bash
# Clone the repository
git clone [repository-url]
cd code-dock

# Set up environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your settings

# Start the server
python web_server.py

# Access web interface
# Open http://localhost:30089 in your browser
```

For Docker deployment:

```bash
# Navigate to deployment directory
cd code-dock-deploy

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Start container
docker-compose up -d
```

For detailed instructions, see the [Installation Guide](docs/INSTALLATION.md) and [Docker Deployment](docs/DOCKER_DEPLOYMENT.md).

## 📦 Project Structure

```
code-dock/
├── api.py                # Main API implementation
├── web_server.py         # Web server setup
├── code_dock/            # Core functionality
│   ├── strong_search_agent.py  # LLM-powered search
│   ├── treesitter.py     # Code parsing
│   ├── indexer.py        # Codebase indexing
│   └── ...
├── web/                  # Frontend implementation
├── code_dock_mcp/        # MCP tools
└── code-dock-deploy/     # Docker deployment files
```

## 📝 License

MIT

---

# Code Dock - 智能代码搜索与探索平台

<div align="right">
  <a href="#code-dock---intelligent-code-search-and-exploration-platform">English</a> | 
  <a href="#code-dock---智能代码搜索与探索平台">中文</a>
</div>

Code Dock 是一个全面的代码搜索、探索和分析解决方案，通过AI驱动的搜索功能实现与代码库的无缝交互。


## 📚 文档

详细文档请参考：

- [安装指南](docs/INSTALLATION_CN.md) - 详细的安装说明
- [用户指南](docs/USER_GUIDE_CN.md) - 如何使用平台
- [API参考](docs/API_REFERENCE_CN.md) - API端点文档
- [MCP工具指南](docs/MCP_GUIDE_CN.md) - 通过MCP实现LLM集成
- [Docker部署](docs/DOCKER_DEPLOYMENT_CN.md) - 容器化部署
- [开发指南](docs/DEVELOPMENT_CN.md) - 如何贡献代码

## 🌟 功能特性

- **多种搜索模式**
  - 标准语义搜索（基于RAG）
  - 高级AI驱动搜索（LLM辅助）
  - 基于文本的关键词搜索
  
- **代码理解**
  - 抽象语法树（AST）可视化
  - 符号引用追踪
  - 文件和目录浏览
  
- **丰富的用户界面**
  - 交互式Web界面
  - 基于WebSocket的实时搜索反馈
  - 可视化代码结构探索
  
- **LLM集成**
  - MCP（Model Context Protocol）工具实现LLM直接交互
  - 支持Claude、通义千问、GPT-4等大型语言模型
  - 基于代理的智能探索

## 🏗️ 系统架构

系统由三个主要组件组成：

1. **后端（Python）**
   - 基于FastAPI的核心搜索和索引引擎
   - 使用Tree-sitter进行多语言代码解析
   - 使用LanceDB向量数据库存储嵌入向量
   - 兼容OpenAI和VoyageAI的嵌入生成

2. **Web前端**
   - 现代HTML/CSS/JavaScript界面
   - 基于WebSocket的实时通信
   - 交互式可视化组件

3. **MCP集成**
   - 用于无缝LLM集成的工具
   - 支持Claude Desktop App
   - 丰富的代码库探索工具集

## 🚀 快速开始

```bash
# 克隆仓库
git clone [仓库地址]
cd code-dock

# 设置环境
python -m venv venv
source venv/bin/activate  # Windows系统: venv\Scripts\activate
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑.env设置

# 启动服务器
python web_server.py

# 访问Web界面
# 在浏览器中打开 http://localhost:30089
```

Docker部署：

```bash
# 进入部署目录
cd code-dock-deploy

# 配置环境
cp .env.example .env
# 编辑.env设置

# 启动容器
docker-compose up -d
```

详细说明请参阅[安装指南](docs/INSTALLATION_CN.md)和[Docker部署](docs/DOCKER_DEPLOYMENT_CN.md)。

## 📦 项目结构

```
code-dock/
├── api.py                # 主要API实现
├── web_server.py         # Web服务器设置
├── code_dock/            # 核心功能
│   ├── strong_search_agent.py  # LLM驱动搜索
│   ├── treesitter.py     # 代码解析
│   ├── indexer.py        # 代码库索引
│   └── ...
├── web/                  # 前端实现
├── code_dock_mcp/        # MCP工具
└── code-dock-deploy/     # Docker部署文件
```

## 📝 许可证

MIT 