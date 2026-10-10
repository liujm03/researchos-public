@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\share_launcher.ps1" -Action stop
if errorlevel 1 (
  echo Operation failed. Read INSTALL.md and inspect local logs.
  pause
  exit /b 1
)
