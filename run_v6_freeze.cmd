@echo off
setlocal
cd /d "%~dp0"
python scripts\freeze_v6_model.py
exit /b %ERRORLEVEL%
