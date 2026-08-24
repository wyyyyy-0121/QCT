@echo off
setlocal
cd /d "%~dp0"
python scripts\run_v6_blind_lock.py %*
exit /b %ERRORLEVEL%
