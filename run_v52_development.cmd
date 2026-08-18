@echo off
setlocal
cd /d "%~dp0"

set "VARIANT=%~1"
if "%VARIANT%"=="" goto usage
if /I not "%VARIANT%"=="a" if /I not "%VARIANT%"=="b" if /I not "%VARIANT%"=="c" goto usage
set "WORKERS=%~2"
if "%WORKERS%"=="" set "WORKERS=24"
set "OUT=results\v5_2_development_%VARIANT%"

echo [0/6] Rebuilding the deterministic 36-event development red team...
python scripts\build_v52_redteam_manifest.py ^
  --benchmark data\propagationbench_v3_full ^
  --output data\v5_2_redteam\manifest.csv ^
  --force
if errorlevel 1 exit /b %errorlevel%

echo [1/6] V5.2-%VARIANT% on the 18 revealed synthetic development events...
python scripts\run_v52_labeled_development.py ^
  --manifest data\v5_development\manifest.csv ^
  --output %OUT%\synthetic ^
  --variant %VARIANT% ^
  --dataset-role revealed_synthetic_development ^
  --candidate-limit 15 ^
  --workers %WORKERS%
if errorlevel 1 exit /b %errorlevel%

echo [2/6] V5.2-%VARIANT% on the 30-event Enron retrospective safety regression...
python scripts\run_v52_labeled_development.py ^
  --manifest data\external\enron\manifest.csv ^
  --output %OUT%\enron ^
  --variant %VARIANT% ^
  --dataset-role enron_retrospective_safety_regression ^
  --candidate-limit 15 ^
  --workers %WORKERS%
if errorlevel 1 exit /b %errorlevel%

echo [3/6] V5.2-%VARIANT% on the 36-event balanced synthetic red team...
python scripts\run_v52_labeled_development.py ^
  --manifest data\v5_2_redteam\manifest.csv ^
  --output %OUT%\redteam ^
  --variant %VARIANT% ^
  --dataset-role retrospective_synthetic_safety_redteam ^
  --candidate-limit 15 ^
  --workers %WORKERS%
if errorlevel 1 exit /b %errorlevel%

echo [4/6] V5.2-%VARIANT% on all 48 clean controls...
python scripts\run_v52_clean_controls.py ^
  --benchmark data\propagationbench_v3_full ^
  --output %OUT%\clean ^
  --variant %VARIANT% ^
  --candidate-limit 15 ^
  --workers %WORKERS%
if errorlevel 1 exit /b %errorlevel%

echo [5/6] Applying non-interference, traceability, red-team, and clean gates...
python scripts\audit_v52_round.py ^
  --variant %VARIANT% ^
  --synthetic-raw %OUT%\synthetic\v52_raw.csv ^
  --synthetic-reference results\v4_blind_scored\blind_scored_events.csv ^
  --enron-raw %OUT%\enron\v52_raw.csv ^
  --enron-reference results\v4_dev_revision\external_raw.csv ^
  --redteam-raw %OUT%\redteam\v52_raw.csv ^
  --clean-summary %OUT%\clean\v52_clean_summary.json ^
  --output %OUT%\v52_round_audit.json ^
  --record-only
if errorlevel 1 exit /b %errorlevel%

echo [6/6] V5.2-%VARIANT% development round completed.
echo Audit: %CD%\%OUT%\v52_round_audit.json
exit /b 0

:usage
echo Usage: run_v52_development.cmd ^<a^|b^|c^> [workers]
echo Default workers: 24
exit /b 2
