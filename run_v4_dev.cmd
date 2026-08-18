@echo off
setlocal
cd /d "%~dp0"

set "V4_WORKERS=%~1"
if "%V4_WORKERS%"=="" set "V4_WORKERS=16"

echo [v4-dev] Retrospective development only; this is not a new blind test.
echo [v4-dev] Workers: %V4_WORKERS%

python scripts\run_external_evaluation.py ^
  --manifest data\external\enron\manifest.csv ^
  --output results\v4_dev_retrospective ^
  --candidate-limit 15 ^
  --workers %V4_WORKERS% ^
  --methods graph,pattern,formulaguard,formulaguard_v3,formulaguard_v4
if errorlevel 1 exit /b %errorlevel%

python scripts\analyze_external_results.py ^
  --raw results\v4_dev_retrospective\external_raw.csv ^
  --output results\v4_dev_retrospective\external_analysis.json ^
  --minimum-quantitative-events 15
if errorlevel 1 exit /b %errorlevel%

python scripts\audit_v4_development.py ^
  --raw results\v4_dev_retrospective\external_raw.csv ^
  --output results\v4_dev_retrospective\v4_development_audit.json ^
  --expected-events 30
if errorlevel 1 exit /b %errorlevel%

echo V4 retrospective development run finished.
echo Results: %CD%\results\v4_dev_retrospective
