<#
.SYNOPSIS
    One-time setup script for LENNY (ARCHER's own desk, Spec Section 11).
    Run as Administrator on LENNY.

.DESCRIPTION
    1. Validates Administrator elevation and current user session.
    2. Configures Autologon for Col's user account using Sysinternals Autologon.
    3. Configures power settings (disables sleep, screen lock, screen saver, lid close sleep).
    4. Sets up C:\archer_lenny, Python dependencies, and Playwright Chromium.
    5. Configures Windows Firewall to allow TCP 8203 (Hands) and TCP 9222 (CDP) ONLY from Main PC (192.168.4.41).
    6. Registers scheduled task ArcherHands to run at user logon in Col's session.
    7. Starts ARCHER Hands service and displays the 6-digit pairing code.
#>

[CmdletBinding()]
param(
    [string]$MainPcIp = "192.168.4.41",
    [int]$HandsPort = 8203,
    [int]$BrowserPort = 9222,
    [string]$TargetDir = "C:\archer_lenny"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ARCHER - LENNY Desk Setup (Spec Section 11)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Verify Elevation
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This script must be run as Administrator. Please open PowerShell as Administrator and run again."
    exit 1
}

$currentUser = $env:USERNAME
$userDomain = $env:USERDOMAIN
Write-Host "[1/7] Target User Account: $userDomain\$currentUser" -ForegroundColor Green

# 2. Power & Lock Settings
Write-Host "[2/7] Configuring power, sleep, and lock screen settings..." -ForegroundColor Yellow
try {
    # Disable sleep, monitor timeout, and hibernation on AC power
    powercfg /change standby-timeout-ac 0
    powercfg /change monitor-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0

    # Set Lid Close action on AC to Do Nothing (0)
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
    powercfg /setactive SCHEME_CURRENT

    # Disable screen saver and password on resume
    New-Item -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization" -Force | Out-Null
    Set-ItemProperty -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization" -Name "NoLockScreen" -Value 1 -Type DWord
    Set-ItemProperty -Path "HKCU:\Control Panel\Desktop" -Name "ScreenSaveActive" -Value "0"
    Set-ItemProperty -Path "HKCU:\Control Panel\Desktop" -Name "ScreenSaverIsSecure" -Value "0"
    Write-Host "      Power and screen lock disabled successfully." -ForegroundColor Green
} catch {
    Write-Warning "Failed to apply some power settings: $_"
}

# 3. Create Directory Structure
Write-Host "[3/7] Setting up directories at $TargetDir..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
New-Item -ItemType Directory -Path "$TargetDir\artifacts" -Force | Out-Null
New-Item -ItemType Directory -Path "$TargetDir\browser_profile" -Force | Out-Null

# Copy hands.py if present in script folder
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$localHands = Join-Path $scriptDir "lenny\hands.py"
if (-not (Test-Path $localHands)) {
    $localHands = Join-Path $scriptDir "hands.py"
}

if (Test-Path $localHands) {
    Copy-Item -Path $localHands -Destination "$TargetDir\hands.py" -Force
    Write-Host "      Copied hands.py to $TargetDir\hands.py" -ForegroundColor Green
} else {
    Write-Host "      Note: Please ensure hands.py is placed at $TargetDir\hands.py" -ForegroundColor Yellow
}

# 4. Python Environment & Dependencies
Write-Host "[4/7] Checking Python and installing dependencies..." -ForegroundColor Yellow
$pythonExe = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    Write-Host "      Python not found on PATH. Attempting winget install..." -ForegroundColor Yellow
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    $pythonExe = "C:\Program Files\Python311\python.exe"
}

Write-Host "      Using Python: $pythonExe" -ForegroundColor Green
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install fastapi uvicorn websockets pillow mss pywinauto pywin32 comtypes playwright loguru
& $pythonExe -m playwright install chromium

# 5. Windows Firewall Rules (Restricted to Main PC IP)
Write-Host "[5/7] Configuring Windows Firewall (Restricted strictly to Main PC: $MainPcIp)..." -ForegroundColor Yellow
Remove-NetFirewallRule -DisplayName "ARCHER_Hands_8203" -ErrorAction SilentlyContinue | Out-Null
Remove-NetFirewallRule -DisplayName "ARCHER_CDP_9222" -ErrorAction SilentlyContinue | Out-Null

New-NetFirewallRule -DisplayName "ARCHER_Hands_8203" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $HandsPort `
    -RemoteAddress $MainPcIp `
    -Action Allow `
    -Description "Inbound ARCHER Hands control from Main PC" | Out-Null

New-NetFirewallRule -DisplayName "ARCHER_CDP_9222" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $BrowserPort `
    -RemoteAddress $MainPcIp `
    -Action Allow `
    -Description "Inbound Chrome DevTools Protocol from Main PC" | Out-Null

Write-Host "      Firewall rules active for ports $HandsPort and $BrowserPort." -ForegroundColor Green

# 6. Sysinternals Autologon Configuration
Write-Host "[6/7] Configuring Autologon for $currentUser..." -ForegroundColor Yellow
Write-Host "      Autologon ensures ARCHER's desk restores automatically after restarts." -ForegroundColor Cyan
$autologonExe = "$TargetDir\Autologon.exe"
if (-not (Test-Path $autologonExe)) {
    try {
        $autologonZip = "$TargetDir\Autologon.zip"
        Invoke-WebRequest -Uri "https://download.sysinternals.com/files/AutoLogon.zip" -OutFile $autologonZip -UseBasicParsing
        Expand-Archive -Path $autologonZip -DestinationPath $TargetDir -Force
        Remove-Item $autologonZip -Force
    } catch {
        Write-Warning "Could not download Autologon directly: $_. You can configure Autologon manually."
    }
}

if (Test-Path $autologonExe) {
    Write-Host "      Running Sysinternals Autologon GUI..." -ForegroundColor Green
    Write-Host "      Enter your Windows password in the Autologon dialog and click 'Enable'." -ForegroundColor Cyan
    Start-Process -FilePath $autologonExe -Wait
} else {
    Write-Host "      Autologon tool not found; configuring registry Autologon directly." -ForegroundColor Yellow
    $regPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    Set-ItemProperty -Path $regPath -Name "AutoAdminLogon" -Value "1"
    Set-ItemProperty -Path $regPath -Name "DefaultUserName" -Value $currentUser
    Set-ItemProperty -Path $regPath -Name "DefaultDomainName" -Value $userDomain
}

# 7. Scheduled Task for ARCHER Hands at Logon
Write-Host "[7/7] Registering ArcherHands scheduled task..." -ForegroundColor Yellow
$taskName = "ArcherHands"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "$TargetDir\hands.py" -WorkingDirectory $TargetDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$userDomain\$currentUser"
$principal = New-ScheduledTaskPrincipal -UserId "$userDomain\$currentUser" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Write-Host "      Scheduled task $taskName registered to start at logon." -ForegroundColor Green

# Start Hands service now to get pairing code
Write-Host "`nStarting ARCHER Hands Service to generate pairing code..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName

Start-Sleep -Seconds 3

# Read token and code if generated
$tokenFile = "$TargetDir\lenny_token.json"
if (Test-Path $tokenFile) {
    $tokenJson = Get-Content $tokenFile | ConvertFrom-Json
    Write-Host "`n==========================================================" -ForegroundColor Green
    Write-Host " LENNY SETUP COMPLETE!" -ForegroundColor Green
    Write-Host " Hands Service Token: $($tokenJson.token)" -ForegroundColor White
    Write-Host " Main PC Inbound Access: $MainPcIp allowed on $HandsPort and $BrowserPort" -ForegroundColor White
    Write-Host "==========================================================" -ForegroundColor Green
} else {
    Write-Host "`nSetup complete! Check the Hands console window or logs for the 6-digit pairing code." -ForegroundColor Green
}
