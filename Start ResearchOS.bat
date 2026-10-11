@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start ResearchOS.ps1"
if errorlevel 1 (
  echo.
  pause
)
