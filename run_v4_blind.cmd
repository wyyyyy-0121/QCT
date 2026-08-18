@echo off
setlocal
cd /d "%~dp0"

python scripts\run_v4_blind_predictions.py ^
  --manifest data\blind_v4\blind_manifest.csv ^
  --config research\frozen_config_v4.json ^
  --output results\v4_blind_locked ^
  --workers 16
if errorlevel 1 exit /b %errorlevel%

echo V4 blind predictions are hash-locked.
echo Do not reveal labels until this command finishes successfully.
echo Lock: %CD%\results\v4_blind_locked\prediction_lock.json
