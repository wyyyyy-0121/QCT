@echo off
setlocal
cd /d "%~dp0"

python scripts\run_v4_v52_blind_100_lock.py ^
  --manifest data\v4_v52_blind\public\manifest.csv ^
  --v4-config research\frozen_config_v4.json ^
  --v52-config research\frozen_config_v52.json ^
  --output results\v4_v52_independent_100_locked ^
  --expected-events 100 ^
  --commitment research\V4_V52_INDEPENDENT_100_COMMITMENT.json ^
  --public-precommit data\v4_v52_blind\public\secret_precommit_sha256.txt ^
  %*
if errorlevel 1 exit /b %errorlevel%

echo Joint V4 and V5.2 predictions for 100 cases are hash-locked.
echo Do not release the Batch-2 labels before this command succeeds.
echo Lock: %CD%\results\v4_v52_independent_100_locked\prediction_lock.json
