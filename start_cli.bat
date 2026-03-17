@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python virtual environment not found: .venv
  echo Please run: python -m venv .venv
  pause
  exit /b 1
)

echo [INFO] Starting CLI mode...
".venv\Scripts\python.exe" run.py --module strategy

if errorlevel 1 (
  echo [ERROR] CLI startup failed.
  pause
  exit /b 1
)

endlocal
