@echo off
REM start.bat — Windows launcher for Study Agent
REM Double-click this file to start the agent

cd /d "%~dp0"

echo.
echo   Study Agent — Starting up...
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found.
    echo   Install it from: https://www.python.org/downloads/
    echo   Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Run the agent from the virtual environment
if exist ".venv\Scripts\python.exe" (
    .\my-venv\Scripts\python.exe main.py %*
) else (
    echo   ERROR: Virtual environment not found.
    echo   Run the setup script first.
    pause
    exit /b 1
)

REM Run the agent
python main.py %*

REM Keep window open if there was an error
if errorlevel 1 (
    echo.
    pause
)
