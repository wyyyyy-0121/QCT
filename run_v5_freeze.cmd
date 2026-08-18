@echo off
setlocal
cd /d "%~dp0"

python scripts\freeze_v5_model.py ^
  --synthetic results\v5_development_synthetic ^
  --enron results\v5_development_enron ^
  --clean results\v5_development_clean ^
  --prerequisite-audit results\v5_development_audit\prerequisite_audit.json ^
  --audit results\v5_development_audit\v5_development_audit.json ^
  --output research\frozen_config_v5.json
if errorlevel 1 exit /b %errorlevel%

echo V5 model frozen. New independent validation is still required.
echo Config: %CD%\research\frozen_config_v5.json
