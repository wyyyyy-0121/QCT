@echo off
setlocal
cd /d "%~dp0"
if "%~2"=="" (
  echo Usage: run_external.cmd manifest.csv output_folder
  exit /b 2
)
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%FG_PYTHON%" (
  "%FG_PYTHON%" scripts\run_external_evaluation.py --manifest "%~1" --output "%~2"
) else (
  python scripts\run_external_evaluation.py --manifest "%~1" --output "%~2"
)
exit /b %ERRORLEVEL%

