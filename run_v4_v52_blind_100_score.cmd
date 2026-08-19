@echo off
setlocal
cd /d "%~dp0"

python scripts\score_v4_v52_blind_100.py ^
  --lock results\v4_v52_independent_100_locked\prediction_lock.json ^
  --labels D:\FormulaGuard_Blind_Labels_100\v4_v52_labels.csv ^
  --exceptions D:\FormulaGuard_Blind_Labels_100\v4_v52_exceptions.csv ^
  --output results\v4_v52_independent_100_scored ^
  --expected-events 100 ^
  --commitment research\V4_V52_INDEPENDENT_100_COMMITMENT.json
if errorlevel 1 exit /b %errorlevel%

echo Independent 100-case scoring finished.
echo Summary: %CD%\results\v4_v52_independent_100_scored\independent_summary.json
