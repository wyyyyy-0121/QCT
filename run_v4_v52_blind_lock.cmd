@echo off
setlocal
cd /d "%~dp0"

python scripts\run_v4_v52_blind_lock.py ^
  --manifest data\v4_v52_blind\public\manifest.csv ^
  --v4-config research\frozen_config_v4.json ^
  --v52-config research\frozen_config_v52.json ^
  --output results\v4_v52_independent_locked ^
  %*
if errorlevel 1 exit /b %errorlevel%

echo Joint V4 and V5.2 predictions are hash-locked.
echo Labels may be released only after this command succeeds.
echo Lock: %CD%\results\v4_v52_independent_locked\prediction_lock.json
