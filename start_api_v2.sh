#!/bin/bash
# V2 API 启动脚本（Linux / Render）
set -e

# 从 .env.example 创建 .env（如果不存在）
if [ ! -f .env ]; then
    echo "[提示] 未找到 .env 文件，正在从 .env.example 创建..."
    cp .env.example .env
    echo "[提示] 请编辑 .env 文件填入 LLM_API_KEY 等配置后重新启动。"
fi

PORT=${PORT:-8000}
echo "启动 V2 API 服务，端口: $PORT"
exec python -m uvicorn src.api.app:app --host 0.0.0.0 --port $PORT
