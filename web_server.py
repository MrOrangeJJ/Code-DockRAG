#!/usr/bin/env python3
"""
web_server.py - 提供Web UI的前端服务器
只负责提供静态文件，所有API请求由api.py处理
"""

import os
import logging
import sys
import socket
import subprocess
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

# 配置日志
log_path = os.getenv("LOG_PATH", "logs")
os.makedirs(log_path, exist_ok=True)

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(os.path.join(log_path, "web_server.log"), encoding="utf-8"),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger("WebUIServer")

# Web服务器端口
WEB_PORT = int(os.getenv("WEB_PORT", "30090"))
# API服务器端口
API_PORT = int(os.getenv("API_PORT", "30089"))

# 创建FastAPI应用
app = FastAPI(
    title="Code Dock Web UI",
    description="提供Code Dock的Web界面",
    version="1.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有源访问，生产环境应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def read_root():
    """提供主页HTML，并动态注入API端口配置"""
    try:
        # 读取HTML内容
        with open("web/index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        
        # 在</head>前注入API配置
        api_config = f"""
        <script>
            // 由服务器动态注入的API配置
            window.CODE_DOCK_CONFIG = {{
                API_PORT: {API_PORT},
                WEB_PORT: {WEB_PORT}
            }};
        </script>
        """
        
        # 将配置注入到HTML中
        html_content = html_content.replace("</head>", f"{api_config}</head>")
        
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"无法加载主页: {e}")
        return HTMLResponse(content="<h1>代码库搜索系统</h1><p>Web界面无法加载，请检查web目录</p>")

# 挂载静态文件
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# 启动信息
@app.on_event("startup")
async def startup_event():
    """服务器启动时执行"""
    logger.info(f"Web UI服务器启动在端口 {WEB_PORT}")
    logger.info(f"请访问 http://localhost:{WEB_PORT} 以使用Web界面")
    logger.info(f"所有API请求应发送到 http://localhost:{API_PORT}")

# 运行服务器
if __name__ == "__main__":
    # 检查端口是否被占用
    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0
            
    # 如果端口被占用，尝试终止进程
    if is_port_in_use(WEB_PORT):
        print(f"端口 {WEB_PORT} 已被占用，尝试终止相关进程...")
        try:
            if sys.platform.startswith('win'):
                subprocess.run(f"FOR /F \"tokens=5\" %P IN ('netstat -ano ^| find \"{WEB_PORT}\"') DO taskkill /F /PID %P", shell=True)
            else:
                subprocess.run(f"lsof -i :{WEB_PORT} -t | xargs kill -9", shell=True)
            print(f"端口 {WEB_PORT} 已释放")
        except Exception as e:
            print(f"无法释放端口: {e}")
            sys.exit(1)
    
    logger.info(f"启动Web UI服务器在端口 {WEB_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT) 