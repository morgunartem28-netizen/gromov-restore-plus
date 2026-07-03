@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "build\build_release.ps1"
if errorlevel 1 (
    echo.
    echo Ошибка сборки.
    pause
    exit /b 1
)

echo.
echo Готово: dist\GROMOV-RestorePlus-Setup.exe
pause
