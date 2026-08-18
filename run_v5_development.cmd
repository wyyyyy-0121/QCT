@echo off
setlocal
cd /d "%~dp0"

echo [1/7] Verifying frozen V4 sources and preregistered V5 inputs...
python scripts\verify_v5_prerequisites.py ^
  --output results\v5_development_audit\prerequisite_audit.json
if errorlevel 1 exit /b %errorlevel%

echo [2/7] Evaluating V5 only on the 18 revealed synthetic development events...
python scripts\run_v5_external_evaluation.py ^
  --manifest data\v5_development\manifest.csv ^
  --output results\v5_development_synthetic ^
  --candidate-limit 15 ^
  --workers 16
if errorlevel 1 exit /b %errorlevel%

echo [3/7] Merging V5 with the locked five-method synthetic evidence...
python scripts\merge_v5_development_results.py ^
  --reference results\v4_blind_scored\blind_scored_events.csv ^
  --v5 results\v5_development_synthetic\v5_raw.csv ^
  --output results\v5_development_synthetic\external_raw.csv
if errorlevel 1 exit /b %errorlevel%

echo [4/7] Evaluating V5 only on the 30-event Enron safety regression...
python scripts\run_v5_external_evaluation.py ^
  --manifest data\external\enron\manifest.csv ^
  --output results\v5_development_enron ^
  --candidate-limit 15 ^
  --workers 16
if errorlevel 1 exit /b %errorlevel%

echo [5/7] Merging V5 with the locked five-method Enron evidence...
python scripts\merge_v5_development_results.py ^
  --reference results\v4_dev_revision\external_raw.csv ^
  --v5 results\v5_development_enron\v5_raw.csv ^
  --output results\v5_development_enron\external_raw.csv
if errorlevel 1 exit /b %errorlevel%

echo [6/7] Evaluating 48 clean-workbook V5 confirmation controls...
python scripts\run_v5_clean_controls.py ^
  --benchmark data\propagationbench_v3_full ^
  --output results\v5_development_clean ^
  --candidate-limit 15 ^
  --workers 16
if errorlevel 1 exit /b %errorlevel%

echo [7/7] Applying all preregistered V5 gates...
python scripts\audit_v5_development.py ^
  --synthetic-raw results\v5_development_synthetic\external_raw.csv ^
  --synthetic-reference results\v4_blind_scored\blind_scored_events.csv ^
  --enron-raw results\v5_development_enron\external_raw.csv ^
  --enron-reference results\v4_dev_revision\external_raw.csv ^
  --clean-summary results\v5_development_clean\v5_clean_summary.json ^
  --prerequisite-audit results\v5_development_audit\prerequisite_audit.json ^
  --output results\v5_development_audit\v5_development_audit.json
if errorlevel 1 exit /b %errorlevel%

echo V5 development run passed all preregistered gates.
echo Audit: %CD%\results\v5_development_audit\v5_development_audit.json
