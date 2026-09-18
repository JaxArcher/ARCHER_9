# Installs the ARCHER Observer Service as an auto-starting Windows
# Service via NSSM, so ambient observation (Reolink motion-triggered
# scene/person analysis + the staleness/neglect reasoning pass) runs
# independently of the desktop app or browser client -- starting at PC
# boot, before you ever log into ARCHER itself (Col's call, 2026-09-16).
#
# One-time setup, needs Administrator PowerShell.
#
# Prerequisites:
#   1. NSSM on PATH. If you don't have it:
#        winget install nssm
#      (or download from https://nssm.cc/download and add it to PATH)
#   2. `ollama` on PATH (already needed for ARCHER generally).
#   3. Run this script from an elevated (Administrator) PowerShell.
#
# What it does: registers `python -m archer.observer_service` as a
# Windows Service named "ArcherObserver", set to start automatically at
# boot, with stdout/stderr logged to D:\ARCHER_9\logs\.
#
# To undo: run uninstall_observer_service.ps1.

$ErrorActionPreference = "Stop"

$ArcherRoot = "D:\ARCHER_9"
$ArcherSrc = Join-Path $ArcherRoot "src"
$LogDir = Join-Path $ArcherRoot "logs"
$ServiceName = "ArcherObserver"

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Error "nssm not found on PATH. Install it first: winget install nssm (then reopen this terminal)."
    exit 1
}

$PythonExe = Join-Path $ArcherRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Venv python not found at $PythonExe. Run: python -m venv .venv  then  .venv\Scripts\pip install -e ."
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# If a previous attempt already registered the service (e.g. with the
# wrong Python resolved before this script hardcoded the venv path), wipe
# it first -- otherwise `nssm install` below fails with "service already
# exists" and the script would silently keep running against whatever
# executable path that stale registration had, since only AppDirectory/
# stdout/stderr get touched below, never the executable itself.
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Existing '$ServiceName' service found -- removing it first so this run is clean..."
    nssm stop $ServiceName 2>$null
    nssm remove $ServiceName confirm 2>$null
    Start-Sleep -Seconds 1
}

Write-Host "Installing '$ServiceName' service..."
Write-Host "  Python:  $PythonExe"
Write-Host "  Command: -m archer.observer_service"
Write-Host "  Workdir: $ArcherSrc"

nssm install $ServiceName $PythonExe "-m archer.observer_service"
nssm set $ServiceName AppDirectory $ArcherSrc
nssm set $ServiceName AppStdout (Join-Path $LogDir "observer_service_stdout.log")
nssm set $ServiceName AppStderr (Join-Path $LogDir "observer_service_stderr.log")
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 10485760
nssm set $ServiceName Start SERVICE_AUTO_START
nssm set $ServiceName DisplayName "ARCHER Observer Service"
nssm set $ServiceName Description "Always-on ambient observation for ARCHER (Reolink motion-triggered scene/person analysis + neglect detection). Independent of the ARCHER desktop app / browser client."

Write-Host "Starting '$ServiceName'..."
nssm start $ServiceName

Write-Host ""
Write-Host "Done. The service will now start automatically every time this PC boots."
Write-Host "Check status:  nssm status $ServiceName"
Write-Host "View logs:     $LogDir\observer_service_stdout.log"
Write-Host "Stop it:       nssm stop $ServiceName"
Write-Host "Remove it:     .\uninstall_observer_service.ps1"
