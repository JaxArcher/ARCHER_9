# Unregisters the ArcherLaunchOnVoice scheduled task (Phase 2c).
# Run from an elevated (Administrator) PowerShell session.

$TaskName = "ArcherLaunchOnVoice"

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Write-Host "Task '$TaskName' is not installed -- nothing to remove."
    exit 0
}

Write-Host "Removing scheduled task '$TaskName'..." -ForegroundColor Cyan
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Task '$TaskName' removed." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to remove task '$TaskName': $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
