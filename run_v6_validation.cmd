@echo off
setlocal
cd /d "%~dp0"
python scripts\run_v6_validation.py %*
exit /b %ERRORLEVEL%
