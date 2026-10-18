@echo off
chcp 65001 >nul
REM ============================================================
REM  启动命名隧道 phenoage（读取 C:\Users\<用户>\.cloudflared\config.yml
REM  中的转发规则，把 medicalcare.work 转发到本机 8000 端口）
REM  前提：
REM    1) 已完成 cloudflared tunnel login
REM    2) 已存在 C:\Users\<用户>\.cloudflared\config.yml
REM    3) 确保 start.bat 已在另一个窗口运行（8000 端口已启动）
REM ============================================================

cd /d "%~dp0"
"%~dp0cloudflared.exe" tunnel run phenoage

pause
