@echo off
:: ARCHER One-Click Launcher (Browser-only mode, no desktop GUI)
:: Double-click this file to start all services and launch ARCHER in
:: web-only mode -- use the browser client instead of the desktop app.

title ARCHER Launcher (Web)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-ARCHER.ps1" -WebOnly

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] ARCHER exited with code %ERRORLEVEL%
    pause
)
