# Registers the ArcherObserverRestart scheduled task.
#
# Allows non-elevated processes (including Antigravity and user scripts)
# to restart the ArcherObserver Windows service on-demand via:
#   schtasks /run /tn "ArcherObserverRestart"
#
# Run once from an elevated (Administrator) PowerShell session.

$ErrorActionPreference = "Stop"

$TaskName = "ArcherObserverRestart"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ARCHER Observer Service Restart Task Setup" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Task Name:   $TaskName"
Write-Host "Action:      powershell.exe -NoProfile -Command `"Restart-Service ArcherObserver`""
Write-Host "Run As:      NT AUTHORITY\SYSTEM (Highest Privileges)"
Write-Host ""

# Check Admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[ERROR] This script must be run from an elevated (Administrator) PowerShell." -ForegroundColor Red
    exit 1
}

# Replace an existing copy of the task, if any.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Existing task '$TaskName' found. Replacing..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Host "Registering scheduled task '$TaskName'..." -ForegroundColor Cyan

try {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"Restart-Service ArcherObserver`""
    $principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Principal $principal -Settings $settings `
        -Description "ARCHER: restarts the ArcherObserver service with elevated privileges on demand." | Out-Null
} catch {
    Write-Host "[ERROR] Failed to register the task: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Usage:" -ForegroundColor Gray
Write-Host "  To restart the observer service from any terminal without prompting:" -ForegroundColor Gray
Write-Host "      schtasks /run /tn `"$TaskName`"" -ForegroundColor Yellow
Write-Host ""
