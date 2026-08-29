@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%FG_PYTHON%" set "FG_PYTHON=python"

"%FG_PYTHON%" scripts\run_v5_core_r2_retrospective.py ^
  --errors data\v5_core_validation ^
  --clean data\v5_core_clean ^
  --output results\v5_core_r2_r2_retrospective_full ^
  --workers 24 ^
  --config research\V5_CORE_R2_R2_CONFIG.json ^
  --resume
exit /b %ERRORLEVEL%
