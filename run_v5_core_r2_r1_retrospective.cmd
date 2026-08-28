@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%FG_PYTHON%" (
  "%FG_PYTHON%" scripts\run_v5_core_r2_retrospective.py --output results\v5_core_r2_r1_retrospective_full --config research\V5_CORE_R2_R1_CONFIG.json %*
) else (
  python scripts\run_v5_core_r2_retrospective.py --output results\v5_core_r2_r1_retrospective_full --config research\V5_CORE_R2_R1_CONFIG.json %*
)
exit /b %ERRORLEVEL%
