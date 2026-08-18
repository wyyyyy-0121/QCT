@echo off
setlocal
cd /d "%~dp0"

set "V4_WORKERS=%~1"
if "%V4_WORKERS%"=="" set "V4_WORKERS=16"

echo [v4-r1] One documented model revision; retrospective development only.
echo [v4-r1] Graph-safe two-lane fusion; all counterfactual thresholds unchanged.
echo [v4-r1] Workers: %V4_WORKERS%

python scripts\run_external_evaluation.py ^
  --manifest data\external\enron\manifest.csv ^
  --output results\v4_dev_revision ^
  --candidate-limit 15 ^
  --workers %V4_WORKERS% ^
  --methods graph,pattern,formulaguard,formulaguard_v3,formulaguard_v4
if errorlevel 1 exit /b %errorlevel%

python scripts\analyze_external_results.py ^
  --raw results\v4_dev_revision\external_raw.csv ^
  --output results\v4_dev_revision\external_analysis.json ^
  --minimum-quantitative-events 15
if errorlevel 1 exit /b %errorlevel%

python scripts\audit_v4_development.py ^
  --raw results\v4_dev_revision\external_raw.csv ^
  --output results\v4_dev_revision\v4_development_audit.json ^
  --expected-events 30
if errorlevel 1 exit /b %errorlevel%

echo V4-R1 retrospective development run finished.
echo Results: %CD%\results\v4_dev_revision
