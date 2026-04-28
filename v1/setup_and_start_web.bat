@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv
    pause
    exit /b 1
  )
)

echo [INFO] Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed.
  echo If you use proxy, set HTTP_PROXY/HTTPS_PROXY first.
  pause
  exit /b 1
)

echo [INFO] Launching Streamlit...
".venv\Scripts\python.exe" -m streamlit run v1\streamlit_app.py

endlocal
