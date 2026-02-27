@echo off
:: ARCHER One-Click Launcher
:: Double-click this file to start all services and launch ARCHER.

title ARCHER Launcher

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-ARCHER.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] ARCHER exited with code %ERRORLEVEL%
    pause
)
