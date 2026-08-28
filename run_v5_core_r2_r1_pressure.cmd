@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%FG_PYTHON%" set "FG_PYTHON=python"

rem Both cohorts have already been revealed.  This is retrospective safety
rem pressure testing, never blind validation and never a tuning loop.
"%FG_PYTHON%" scripts\run_v5_core_r2_pressure.py ^
  --root data\v4_v52_blind\public ^
  --events results\v4_v52_independent_100_scored\independent_scored_events.csv ^
  --workbook-manifest data\v4_v52_blind\public\manifest.csv ^
  --config research\V5_CORE_R2_R1_CONFIG.json ^
  --output results\v5_core_r2_r1_pressure\historical_100 ^
  --workers 24 ^
  --resume
if errorlevel 1 exit /b %ERRORLEVEL%

"%FG_PYTHON%" scripts\run_v5_core_r2_pressure.py ^
  --root data\external\enron ^
  --events data\external\enron\manifest.csv ^
  --config research\V5_CORE_R2_R1_CONFIG.json ^
  --output results\v5_core_r2_r1_pressure\enron ^
  --workers 24 ^
  --resume
if errorlevel 1 exit /b %ERRORLEVEL%

"%FG_PYTHON%" scripts\audit_v5_core_r2_pressure.py ^
  --historical-100 results\v5_core_r2_r1_pressure\historical_100\pressure_summary.json ^
  --enron results\v5_core_r2_r1_pressure\enron\pressure_summary.json ^
  --development-audit results\v5_core_r2_r1_retrospective_full\r2_retrospective_audit.json ^
  --output results\v5_core_r2_r1_pressure\pressure_safety_audit.json
exit /b %ERRORLEVEL%
