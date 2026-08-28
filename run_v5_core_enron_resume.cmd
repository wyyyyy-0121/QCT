@echo off
setlocal
cd /d "%~dp0"
set "FG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%FG_PYTHON%" set "FG_PYTHON=python"
"%FG_PYTHON%" scripts\run_v5_core_enron.py ^
  --rule-config results\v5_core_development\config\v5_core_rule_config.json ^
  --learned-config results\v5_core_development\config\v5_core_learned_config.json ^
  --output results\v5_core_development\enron ^
  --workers 24 ^
  --resume
exit /b %ERRORLEVEL%
