@echo off
cd /d "%~dp0"
python run.py --demo --open
if errorlevel 1 pause
