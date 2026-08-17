@echo off
setlocal
cd /d "%~dp0"

python scripts\verify_v3_real_freeze.py ^
  --config research\frozen_config_v3_real.json ^
  --test-manifest data\external\enron\test_manifest.csv
if errorlevel 1 exit /b %errorlevel%

python scripts\run_external_evaluation.py ^
  --manifest data\external\enron\test_manifest.csv ^
  --output results\enron_test_v3_real ^
  --candidate-limit 15 ^
  --workers 16
if errorlevel 1 exit /b %errorlevel%

python scripts\analyze_external_results.py ^
  --raw results\enron_test_v3_real\external_raw.csv ^
  --output results\enron_test_v3_real\external_analysis.json ^
  --minimum-quantitative-events 15
if errorlevel 1 exit /b %errorlevel%

echo Enron external test finished.
echo Results: %CD%\results\enron_test_v3_real
