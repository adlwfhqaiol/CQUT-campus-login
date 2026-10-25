@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python Launcher。请安装 Python 3.10 或更高版本。
    pause
    exit /b 1
)

py -3 cqut_campus_login.py %*
set "exit_code=%errorlevel%"
if not "%exit_code%"=="0" pause
exit /b %exit_code%
