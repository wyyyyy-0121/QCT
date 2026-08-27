@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%FG_PYTHON%" set "FG_PYTHON=python"
"%FG_PYTHON%" scripts\lock_v5_core_blind.py %*
exit /b %ERRORLEVEL%
