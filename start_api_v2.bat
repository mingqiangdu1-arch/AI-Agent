@echo off
setlocal
cd /d %~dp0

if not exist .env (
  if exist .env.example (
    echo [提示] 未找到 .env 文件，正在从 .env.example 创建...
    copy .env.example .env >nul
    echo [提示] 请编辑 .env 文件填入 LLM_API_KEY 等配置后重新启动。
    pause
    exit /b 1
  )
)

set PORT=8000
for /f "tokens=5" %%p in ('netstat -ano ^| findstr LISTENING ^| findstr :8000') do (
  set PORT=8001
)

if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m uvicorn src.api.app:app --reload --port %PORT%
) else (
  python -m uvicorn src.api.app:app --reload --port %PORT%
)
