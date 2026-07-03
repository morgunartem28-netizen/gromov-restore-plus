@echo off
chcp 65001 >nul
setlocal

echo GROMOV Restore+ — установка драйверов Apple для iPhone
echo.

sc query "Apple Mobile Device Service" >nul 2>&1
if %errorlevel%==0 (
    echo Драйверы Apple уже установлены.
    exit /b 0
)

set "DIR=%~dp0"

if exist "%DIR%AppleApplicationSupport64.msi" (
    echo Установка Apple Application Support...
    msiexec /i "%DIR%AppleApplicationSupport64.msi" /passive /norestart
)

if exist "%DIR%AppleMobileDeviceSupport64.msi" (
    echo Установка Apple Mobile Device Support...
    msiexec /i "%DIR%AppleMobileDeviceSupport64.msi" /passive /norestart
)

sc query "Apple Mobile Device Service" >nul 2>&1
if %errorlevel%==0 (
    echo Готово.
    exit /b 0
)

where winget >nul 2>&1
if %errorlevel%==0 (
    echo Пробую установить через winget...
    winget install --id Apple.AppleMobileDeviceSupport --accept-package-agreements --accept-source-agreements --silent 2>nul
    winget install --id Apple.AppleApplicationSupport --accept-package-agreements --accept-source-agreements --silent 2>nul
)

sc query "Apple Mobile Device Service" >nul 2>&1
if %errorlevel%==0 (
    echo Готово.
    exit /b 0
)

echo.
echo Не удалось установить автоматически.
echo Откройте Microsoft Store и установите «Apple Devices»:
echo https://apps.microsoft.com/detail/9pb2mz1zmb1s
echo.
start "" "https://apps.microsoft.com/detail/9pb2mz1zmb1s"
exit /b 1
