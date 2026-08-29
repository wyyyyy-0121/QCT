@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%FG_PYTHON%" set "FG_PYTHON=python"

rem Both cohorts were revealed before this run. This is a retrospective safety
rem test, not model selection and not independent validation.
"%FG_PYTHON%" scripts\run_v5_core_r2_pressure.py ^
  --root data\v4_v52_blind\public ^
  --events results\v4_v52_independent_100_scored\independent_scored_events.csv ^
  --workbook-manifest data\v4_v52_blind\public\manifest.csv ^
  --config research\V5_CORE_R2_R2_STRUCTURAL_GUARD_CONFIG.json ^
  --output results\v5_core_r2_r2_structural_guard_pressure\historical_100 ^
  --workers 24 ^
  --resume
if errorlevel 1 exit /b %ERRORLEVEL%

"%FG_PYTHON%" scripts\run_v5_core_r2_pressure.py ^
  --root data\external\enron ^
  --events data\external\enron\manifest.csv ^
  --config research\V5_CORE_R2_R2_STRUCTURAL_GUARD_CONFIG.json ^
  --output results\v5_core_r2_r2_structural_guard_pressure\enron ^
  --workers 24 ^
  --resume
if errorlevel 1 exit /b %ERRORLEVEL%

"%FG_PYTHON%" scripts\audit_v5_core_r2_pressure.py ^
  --historical-100 results\v5_core_r2_r2_structural_guard_pressure\historical_100\pressure_summary.json ^
  --enron results\v5_core_r2_r2_structural_guard_pressure\enron\pressure_summary.json ^
  --development-audit results\v5_core_r2_r2_structural_guard_retrospective_full\r2_retrospective_audit.json ^
  --method-label "R2 structural-guard" ^
  --protocol "v5_core_r2_structural_guard_pressure_safety_decision_v1" ^
  --output results\v5_core_r2_r2_structural_guard_pressure\pressure_safety_audit.json
exit /b %ERRORLEVEL%
