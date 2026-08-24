@echo off
setlocal
cd /d "%~dp0"
python scripts\run_v6_smoke.py
exit /b %ERRORLEVEL%
