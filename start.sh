#!/bin/bash
# 启动脚本 - 用于启动API服务器和Web服务器

# 设置PYTHONPATH以确保模块导入正常工作
export PYTHONPATH="$PYTHONPATH:$(pwd)"
echo "PYTHONPATH设置为: $PYTHONPATH"

# 检查端口是否被占用并终止相应进程
check_and_kill_port() {
  local port=$1
  echo "检查端口 $port 是否被占用..."
  if lsof -i :$port -t &> /dev/null; then
    echo "端口 $port 已被占用，正在终止相关进程..."
    lsof -i :$port -t | xargs kill -9
    echo "端口 $port 已释放"
  else
    echo "端口 $port 未被占用"
  fi
}

# 检查并释放API和Web服务器端口
check_and_kill_port 30089
check_and_kill_port 30090

# 确保必要的目录存在
mkdir -p uploads
mkdir -p web/static/css
mkdir -p web/static/js

# 确保日志目录存在
LOG_DIR=$(grep "LOG_PATH" .env 2>/dev/null | cut -d'=' -f2 2>/dev/null || echo "logs")
if [ -n "$LOG_DIR" ]; then
  mkdir -p "$LOG_DIR"
else
  mkdir -p logs
fi

# 启动API服务器（后台运行）
echo "启动API服务器 (端口: 30089)..."
python3 api.py &
API_PID=$!
echo "API服务器进程ID: $API_PID"

# 等待API服务器启动
echo "等待API服务器启动..."
sleep 3

# 启动Web服务器（前台运行）
echo "启动Web服务器 (端口: 30090)..."
python3 web_server.py

# 捕获Ctrl+C并清理后台进程
trap "echo '正在关闭服务...'; kill $API_PID; exit" INT

# 脚本会因为前台的Python命令而保持运行，直到被中断
wait $API_PID # 等待后台进程结束（虽然通常是trap处理）