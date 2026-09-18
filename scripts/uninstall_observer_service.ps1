# Removes the ARCHER Observer Service installed by
# install_observer_service.ps1. Needs Administrator PowerShell.

$ErrorActionPreference = "Stop"
$ServiceName = "ArcherObserver"

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Error "nssm not found on PATH."
    exit 1
}

Write-Host "Stopping '$ServiceName' (if running)..."
nssm stop $ServiceName 2>$null

Write-Host "Removing '$ServiceName'..."
nssm remove $ServiceName confirm

Write-Host "Done. The observer service will no longer start automatically."
Write-Host "You can still run it manually any time with: python -m archer.observer_service"
