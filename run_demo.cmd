@echo off
setlocal
cd /d "%~dp0"
set "FG_MODE=%~1"
if "%FG_MODE%"=="" set "FG_MODE=quick"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%FG_PYTHON%" (
  "%FG_PYTHON%" scripts\demo_case.py --benchmark "data\propagationbench_%FG_MODE%" --output "outputs\demo_%FG_MODE%"
) else (
  python scripts\demo_case.py --benchmark "data\propagationbench_%FG_MODE%" --output "outputs\demo_%FG_MODE%"
)
exit /b %ERRORLEVEL%

