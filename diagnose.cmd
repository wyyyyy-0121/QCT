@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%FG_PYTHON%" (
  "%FG_PYTHON%" run.py %*
) else (
  python run.py %*
)
exit /b %ERRORLEVEL%

