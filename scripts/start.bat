@echo off
chcp 65001 >nul
REM ============================================================
REM  启动 PhenoAge 后端服务（本地监听 127.0.0.1:8000）
REM  首次使用请先执行：pip install -r requirements.txt
REM  并复制 .env.example 为 .env，填入 AI_API_KEY
REM ============================================================

cd /d "%~dp0.."

REM 优先使用项目自带的 .venv（若已创建），否则回退到系统 python / py 启动器
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) else (
    py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
)

:done
pause
