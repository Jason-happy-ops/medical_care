@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  PhenoAge 一键启动：后端 + Cloudflare 隧道
REM  每次开机后双击本文件即可；可重复运行，已启动的部分会自动跳过。
REM   - 后端在后台运行，日志见 logs\backend.log
REM   - 隧道在最小化窗口运行，关闭该窗口会断开公网访问
REM ============================================================

set "ROOT=%~dp0.."

if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"

REM ---- 后端 ----
cd /d "%ROOT%"
netstat -ano | findstr /R ":8000 .*LISTENING" >nul
if %errorlevel%==0 (
    echo [后端] 已在运行（8000 端口）。
) else (
    echo [后端] 正在启动 ...
    "%ROOT%\.venv\Scripts\pythonw.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "%ROOT%\logs\backend.log" 2>&1
)

REM ---- 隧道 ----
cd /d "%~dp0"
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | findstr /I "cloudflared.exe" >nul
if %errorlevel%==0 (
    echo [隧道] 已在运行。
) else (
    echo [隧道] 正在启动 ...
    start "PhenoAge Tunnel" /min "%~dp0cloudflared.exe" tunnel run phenoage
)

echo.
echo 稍候几秒后即可访问：https://medicalcare.work
timeout /t 5 /nobreak >nul
echo.
pause
endlocal
