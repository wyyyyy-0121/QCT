@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%FG_PYTHON%" set "FG_PYTHON=python"
"%FG_PYTHON%" scripts\prepare_v5_core_third_party_pack.py %*
exit /b %ERRORLEVEL%
