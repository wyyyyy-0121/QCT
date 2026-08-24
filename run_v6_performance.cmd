@echo off
setlocal
cd /d "%~dp0"
python scripts\run_v6_performance.py %*
exit /b %ERRORLEVEL%
