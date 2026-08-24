@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=python"
%PYTHON_EXE% scripts\run_v6_round.py %*
exit /b %ERRORLEVEL%
