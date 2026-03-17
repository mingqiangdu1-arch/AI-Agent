@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python virtual environment not found: .venv
  echo Please run: python -m venv .venv
  pause
  exit /b 1
)

echo [INFO] Starting Streamlit web app...
".venv\Scripts\python.exe" -m streamlit run streamlit_app.py

if errorlevel 1 (
  echo [ERROR] Streamlit startup failed.
  pause
  exit /b 1
)

endlocal
