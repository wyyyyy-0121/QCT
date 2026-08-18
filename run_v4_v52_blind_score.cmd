@echo off
setlocal
cd /d "%~dp0"

python scripts\score_v4_v52_blind.py ^
  --lock results\v4_v52_independent_locked\prediction_lock.json ^
  --labels D:\FormulaGuard_Blind_Labels\v4_v52_labels.csv ^
  --exceptions D:\FormulaGuard_Blind_Labels\v4_v52_exceptions.csv ^
  --output results\v4_v52_independent_scored
if errorlevel 1 exit /b %errorlevel%

echo Independent scoring finished.
echo Summary: %CD%\results\v4_v52_independent_scored\independent_summary.json
