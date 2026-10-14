@echo off
REM Start the bot. Keep this window open while the bot runs. Close it or press Ctrl+C to stop.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python -m dispatch_bot
if errorlevel 1 (
  echo.
  echo The bot stopped. If the message above mentions the .env file, fix it first.
  pause
  exit /b 1
)
exit /b 0
