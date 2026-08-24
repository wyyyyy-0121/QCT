@echo off
setlocal
cd /d "%~dp0"
python scripts\score_v6_blind.py %*
exit /b %ERRORLEVEL%
