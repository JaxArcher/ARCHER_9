# Removes the two ARCHER observer services installed by
# install_observer_service.ps1: ArcherObserver, then the CPU-only
# ArcherObserverOllama it depends on. Needs Administrator PowerShell.

$ErrorActionPreference = "Continue"

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "nssm not found on PATH." -ForegroundColor Red
    exit 1
}

foreach ($ServiceName in @("ArcherObserver", "ArcherObserverOllama")) {
    if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
        Write-Host "'$ServiceName' is not installed -- skipping."
        continue
    }
    Write-Host "Stopping '$ServiceName' (if running)..."
    nssm stop $ServiceName 2>&1 | Out-Null
    Write-Host "Removing '$ServiceName'..."
    nssm remove $ServiceName confirm 2>&1 | Out-Null
}

Write-Host "Done. Neither observer service will start automatically any more."
Write-Host "You can still run the observer manually with: python -m archer.observer_service"
Write-Host "(ARCHER starts its own observer Ollama on port 11435 when you launch it.)"
