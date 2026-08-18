@echo off
setlocal
cd /d "%~dp0"

python scripts\select_v52_variant.py ^
  --audit-a results\v5_2_development_a\v52_round_audit.json ^
  --audit-b results\v5_2_development_b\v52_round_audit.json ^
  --audit-c results\v5_2_development_c\v52_round_audit.json ^
  --output results\v5_2_selection.json
if errorlevel 1 exit /b %errorlevel%

python scripts\freeze_v52_model.py ^
  --selection results\v5_2_selection.json ^
  --output research\frozen_config_v52.json
if errorlevel 1 exit /b %errorlevel%

echo V5.2 selected and frozen. Commit the new configuration before blind prediction.
echo Config: %CD%\research\frozen_config_v52.json
