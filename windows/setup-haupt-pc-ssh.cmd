@echo off
rem Doppelklick-Starter: holt sich Adminrechte und fuehrt das PowerShell-Skript aus.
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-haupt-pc-ssh.ps1"
echo.
pause
