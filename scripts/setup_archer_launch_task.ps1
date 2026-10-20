# Registers the ArcherLaunchOnVoice scheduled task.
#
# Bridges Windows Session 0 isolation so the always-on observer service
# (which runs as LocalSystem in Session 0) can launch ARCHER in Col's
# interactive user session when "all systems go" is heard in the room.
#
# Runs:
#   1. At logon: starts ARCHER only if "all systems go" was heard within the last 10 minutes.
#   2. On demand: triggered by the observer service via `schtasks /run /tn "ArcherLaunchOnVoice"`.
#
# Run from an elevated (Administrator) PowerShell session while logged in as Col.
# The task itself runs as Col with normal (not administrator) rights, only while
# he's logged on. To undo: run uninstall_archer_launch_task.ps1.

$ErrorActionPreference = "Stop"

$TaskName   = "ArcherLaunchOnVoice"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArcherRoot = Split-Path -Parent $ScriptDir
$BatPath    = Join-Path $ScriptDir "launch_archer_voice.bat"
$User       = "$env:USERDOMAIN\$env:USERNAME"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ARCHER Voice Launch Task Setup" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Task Name:   $TaskName"
Write-Host "Target User: $User"
Write-Host "Action:      scripts\launch_check.py (via pythonw, or $BatPath)"
Write-Host ""

# Check Admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[ERROR] This script must be run from an elevated (Administrator) PowerShell." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $BatPath)) {
    Write-Host "[ERROR] Batch wrapper not found at: $BatPath" -ForegroundColor Red
    exit 1
}

# Replace an existing copy of the task, if any.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Existing task '$TaskName' found. Replacing..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Runs as Col, only while he's logged on (so it opens windows in his session),
# with normal rights: an ARCHER started by voice must not run as administrator.
# Triggered at Col's logon, and on demand by the observer service
# (schtasks /run /tn ArcherLaunchOnVoice).
Write-Host "Registering scheduled task '$TaskName' for user '$User'..." -ForegroundColor Cyan

try {
    # pythonw (no console window) when the venv has it; the .bat wrapper otherwise.
    $Pythonw = Join-Path $ArcherRoot ".venv\Scripts\pythonw.exe"
    $Check   = Join-Path $ScriptDir "launch_check.py"
    if (Test-Path $Pythonw) {
        $action = New-ScheduledTaskAction -Execute $Pythonw -Argument "`"$Check`" --onlogon" -WorkingDirectory $ArcherRoot
    } else {
        $action = New-ScheduledTaskAction -Execute $BatPath -Argument "--onlogon" -WorkingDirectory $ArcherRoot
    }
    $trigger   = New-ScheduledTaskTrigger -AtLogOn -User $User
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings `
        -Description "ARCHER: start ARCHER when 'all systems go' is heard in the room (Phase 2c)." | Out-Null
} catch {
    Write-Host "[ERROR] Failed to register the task: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Details:" -ForegroundColor Gray
Write-Host "  - Triggers automatically at logon for '$User'."
Write-Host "  - The service triggers it on-demand when 'all systems go' is heard."
Write-Host "  - If ARCHER is already running, it opens ARCHER's page; it never starts a second copy."
Write-Host "  - To test on demand right now, run:" -ForegroundColor Yellow
Write-Host "      schtasks /run /tn `"$TaskName`"" -ForegroundColor Yellow
Write-Host ""
