@echo off
rem AI Usage Monitor - Windows launcher
where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 is required: https://www.python.org/downloads/
    pause
    exit /b 1
)
python start.py
