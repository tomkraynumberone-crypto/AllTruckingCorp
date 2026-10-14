@echo off
REM One-time setup for Windows. Double-click this file.
cd /d "%~dp0"

set PY=py -3
%PY% --version >nul 2>&1 || set PY=python
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Python 3.11 or newer was not found.
  echo Install it from https://www.python.org/downloads/ and TICK "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  %PY% -m venv .venv || (echo Could not create .venv & pause & exit /b 1)
)
echo Installing packages...
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || (echo Package install failed. Check your internet connection. & pause & exit /b 1)

if not exist .env (
  copy .env.example .env >nul
  echo.
  echo Created the file ".env". Opening it now: paste your bot token and admin IDs, save, and close.
  notepad .env
)
echo.
echo Setup finished. Next: double-click run.bat
pause
