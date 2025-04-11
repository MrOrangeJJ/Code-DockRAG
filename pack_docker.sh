#!/bin/bash
# 快速打包脚本 - 将项目打包为x86架构的Docker镜像

set -e  # 遇到错误立即停止

# 默认参数
VERSION="latest"
CLEAN=false
EXPORT=false
ENV_FILE=".env"
IMAGE_NAME="code-dock"

# 解析命令行参数
while [[ $# -gt 0 ]]; do
  case $1 in
    -v|--version)
      VERSION="$2"
      shift 2
      ;;
    -c|--clean)
      CLEAN=true
      shift
      ;;
    -e|--export)
      EXPORT=true
      shift
      ;;
    -env|--environment)
      ENV_FILE="$2"
      shift 2
      ;;
    -n|--name)
      IMAGE_NAME="$2"
      shift 2
      ;;
    -h|--help)
      echo "使用: $0 [选项]"
      echo "选项:"
      echo "  -v, --version VERSION    指定镜像版本 (默认: latest)"
      echo "  -c, --clean              清理已有的容器和镜像"
      echo "  -e, --export             导出镜像为tar文件"
      echo "  -env, --environment FILE 指定环境配置文件 (默认: .env)"
      echo "  -n, --name NAME          指定镜像名称 (默认: code-dock)"
      echo "  -h, --help               显示帮助信息"
      exit 0
      ;;
    *)
      echo "未知参数: $1"
      echo "使用 '$0 --help' 查看帮助"
      exit 1
      ;;
  esac
done

# 显示当前设置
echo "===== 打包配置 ====="
echo "镜像名称: $IMAGE_NAME"
echo "版本: $VERSION"
echo "环境配置: $ENV_FILE"
echo "清理旧容器/镜像: $CLEAN"
echo "导出镜像: $EXPORT"
echo "===================="

# 检查必要文件
if [ ! -f "Dockerfile" ]; then
  echo "错误: Dockerfile 不存在"
  exit 1
fi

if [ ! -f "start.sh" ]; then
  echo "错误: start.sh 不存在"
  exit 1
fi

# 清理旧容器和镜像（如选择）
if [ "$CLEAN" = true ]; then
  echo "清理旧容器和镜像..."
  docker rm -f "${IMAGE_NAME}" 2>/dev/null || true
  docker rmi -f "${IMAGE_NAME}:${VERSION}" 2>/dev/null || true
fi

# 检查是否需要创建目录
for dir in "codebases" "uploads" "logs"; do
  if [ ! -d "$dir" ]; then
    echo "创建目录: $dir"
    mkdir -p "$dir"
  fi
done

# 构建镜像
echo "开始构建x86架构的Docker镜像..."
docker buildx build --platform linux/amd64 -t "${IMAGE_NAME}:${VERSION}" .

# 验证镜像是否创建成功
if [ $? -ne 0 ]; then
  echo "错误: 镜像构建失败"
  exit 1
fi

# 导出镜像（如选择）
if [ "$EXPORT" = true ]; then
  echo "导出镜像为tar文件..."
  OUTPUT_FILE="${IMAGE_NAME}-${VERSION}.tar"
  docker save -o "$OUTPUT_FILE" "${IMAGE_NAME}:${VERSION}"
  echo "镜像已保存到: $OUTPUT_FILE"
  
  # 创建导入脚本
  IMPORT_SCRIPT="import_${IMAGE_NAME}_${VERSION}.sh"
  cat > "$IMPORT_SCRIPT" << EOF
#!/bin/bash
# Docker镜像导入脚本 - ${IMAGE_NAME}:${VERSION}

if [ ! -f "${OUTPUT_FILE}" ]; then
  echo "错误: 镜像文件 ${OUTPUT_FILE} 不存在"
  exit 1
fi

echo "导入Docker镜像..."
docker load -i "${OUTPUT_FILE}"
echo "镜像已导入: ${IMAGE_NAME}:${VERSION}"
EOF
  chmod +x "$IMPORT_SCRIPT"
  echo "导入脚本已生成: $IMPORT_SCRIPT"
fi

# 处理环境变量
ENV_CONFIG=""
if [ -f "$ENV_FILE" ]; then
  echo "从 $ENV_FILE 读取环境变量..."
  ENV_CONFIG="--env-file $ENV_FILE"
  # 复制环境文件到部署包
  cp "$ENV_FILE" "deploy_env_${VERSION}"
else
  echo "警告: 环境配置文件 $ENV_FILE 不存在，将使用默认环境变量"
fi

# 生成部署脚本
DEPLOY_SCRIPT="deploy_${IMAGE_NAME}_${VERSION}.sh"
echo "生成部署脚本: $DEPLOY_SCRIPT"

cat > "$DEPLOY_SCRIPT" << EOF
#!/bin/bash
# Docker部署脚本 - ${IMAGE_NAME}:${VERSION}

set -e  # 遇到错误立即停止

# 创建必要的目录
for dir in "codebases" "uploads" "logs"; do
  if [ ! -d "\$dir" ]; then
    echo "创建目录: \$dir"
    mkdir -p "\$dir"
  fi
done

# 停止并移除旧容器（如果存在）
echo "停止并移除旧容器..."
docker rm -f "${IMAGE_NAME}" 2>/dev/null || true

# 检查环境配置
ENV_CONFIG=""
if [ -f "deploy_env_${VERSION}" ]; then
  ENV_CONFIG="--env-file deploy_env_${VERSION}"
fi

# 启动新容器
echo "启动新容器..."
docker run -d \\
  --name ${IMAGE_NAME} \\
  -p 30089:30089 \\
  -p 30090:30090 \\
  -v "\$(pwd)/codebases:/app/codebases" \\
  -v "\$(pwd)/uploads:/app/uploads" \\
  -v "\$(pwd)/logs:/app/logs" \\
  \$ENV_CONFIG \\
  --platform linux/amd64 \\
  ${IMAGE_NAME}:${VERSION}

echo "===== 部署完成 ====="
echo "API服务器: http://localhost:30089"
echo "Web界面: http://localhost:30090"
echo ""
echo "使用以下命令查看日志:"
echo "docker logs -f ${IMAGE_NAME}"
EOF

chmod +x "$DEPLOY_SCRIPT"
echo "部署脚本已生成: $DEPLOY_SCRIPT"
echo "打包流程完成！" 