@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Не найден .venv
  pause
  exit /b 1
)

start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0src\main.py"
