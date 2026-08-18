@echo off
setlocal
cd /d "%~dp0"

python scripts\freeze_v4_model.py ^
  --results results\v4_dev_revision ^
  --output research\frozen_config_v4.json
if errorlevel 1 exit /b %errorlevel%

echo V4-R1 model frozen.
echo Config: %CD%\research\frozen_config_v4.json
