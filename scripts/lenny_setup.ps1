<#
.SYNOPSIS
    One-time setup script for LENNY (ARCHER's own desk, Spec Section 11).
    Run as Administrator on LENNY.

.DESCRIPTION
    1. Validates Administrator elevation and current user session.
    2. Configures power settings (disables sleep, screen lock, screen saver, lid close sleep).
    3. Sets up C:\archer_lenny, pinned Python dependencies from requirements-lenny.txt, and Playwright Chromium.
    4. Configures program-specific Windows Firewall rules for python.exe (8203) and chrome.exe (9222) ONLY from Main PC (192.168.4.41).
    5. Configures Autologon using Sysinternals Autologon (with Microsoft Authenticode signature verification, no insecure registry fallback).
    6. Registers scheduled task ArcherHands to run at user logon in Col's session.
    7. Starts ARCHER Hands service and displays the 6-digit single-use pairing code.
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

# Copy hands.py and requirements-lenny.txt if present in script folder
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

$localReq = Join-Path $scriptDir "lenny\requirements-lenny.txt"
if (-not (Test-Path $localReq)) {
    $localReq = Join-Path $scriptDir "requirements-lenny.txt"
}
if (Test-Path $localReq) {
    Copy-Item -Path $localReq -Destination "$TargetDir\requirements-lenny.txt" -Force
    Write-Host "      Copied requirements-lenny.txt to $TargetDir\requirements-lenny.txt" -ForegroundColor Green
}

# 4. Python Environment & Pinned Dependencies
Write-Host "[4/7] Checking Python and installing pinned dependencies..." -ForegroundColor Yellow
$pythonExe = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    Write-Host "      Python not found on PATH. Attempting winget install..." -ForegroundColor Yellow
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    $pythonExe = "C:\Program Files\Python311\python.exe"
}

Write-Host "      Using Python: $pythonExe" -ForegroundColor Green
& $pythonExe -m pip install --upgrade pip

$reqTarget = "$TargetDir\requirements-lenny.txt"
if (Test-Path $reqTarget) {
    Write-Host "      Installing pinned dependencies from $reqTarget..." -ForegroundColor Cyan
    & $pythonExe -m pip install -r $reqTarget
} else {
    Write-Host "      requirements-lenny.txt not found; installing pinned package list directly..." -ForegroundColor Yellow
    & $pythonExe -m pip install fastapi==0.115.6 uvicorn==0.34.0 websockets==14.1 pillow==11.1.0 mss==9.0.2 pywinauto==0.6.9 pywin32==311 comtypes==1.4.15 playwright==1.49.1 loguru==0.7.3
}

Write-Host "      Installing Playwright Chromium browser binary..." -ForegroundColor Cyan
& $pythonExe -m playwright install chromium

# Locate Playwright installed chrome.exe for program-specific firewall rule
$pwRoot = Join-Path $env:LOCALAPPDATA "ms-playwright"
$chromeExe = $null
if (Test-Path $pwRoot) {
    $chromeCandidate = Get-ChildItem -Path $pwRoot -Filter "chrome.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($chromeCandidate) {
        $chromeExe = $chromeCandidate.FullName
    }
}
if (-not $chromeExe) {
    $systemChrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    if (Test-Path $systemChrome) {
        $chromeExe = $systemChrome
    }
}

# 5. Windows Firewall Rules (Program-Specific & Restricted to Main PC IP)
Write-Host "[5/7] Configuring Windows Firewall (Program-specific rules restricted to Main PC: $MainPcIp)..." -ForegroundColor Yellow
Remove-NetFirewallRule -DisplayName "ARCHER_Hands_8203" -ErrorAction SilentlyContinue | Out-Null
Remove-NetFirewallRule -DisplayName "ARCHER_CDP_9222" -ErrorAction SilentlyContinue | Out-Null

# Inbound rule specifically for python.exe on port 8203
New-NetFirewallRule -DisplayName "ARCHER_Hands_8203" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $HandsPort `
    -RemoteAddress $MainPcIp `
    -Program $pythonExe `
    -Action Allow `
    -Description "Inbound ARCHER Hands control from Main PC (Program-specific: python.exe)" | Out-Null
Write-Host "      Created program-specific firewall rule for Hands ($pythonExe on port $HandsPort)." -ForegroundColor Green

# Inbound rule specifically for Playwright chrome.exe on port 9222
if ($chromeExe -and (Test-Path $chromeExe)) {
    New-NetFirewallRule -DisplayName "ARCHER_CDP_9222" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $BrowserPort `
        -RemoteAddress $MainPcIp `
        -Program $chromeExe `
        -Action Allow `
        -Description "Inbound Chrome DevTools Protocol from Main PC (Program-specific: chrome.exe)" | Out-Null
    Write-Host "      Created program-specific firewall rule for Chromium ($chromeExe on port $BrowserPort)." -ForegroundColor Green
} else {
    Write-Warning "Playwright chrome.exe not located at firewall setup time; created port-based rule for $BrowserPort."
    New-NetFirewallRule -DisplayName "ARCHER_CDP_9222" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $BrowserPort `
        -RemoteAddress $MainPcIp `
        -Action Allow `
        -Description "Inbound Chrome DevTools Protocol from Main PC" | Out-Null
}

Write-Host "      Firewall rules active and restricted to $MainPcIp. Windows will not prompt for network permissions." -ForegroundColor Green

# 6. Sysinternals Autologon Configuration
Write-Host "[6/7] Configuring Autologon for $currentUser..." -ForegroundColor Yellow
Write-Host "      Autologon ensures ARCHER's desk restores automatically after restarts." -ForegroundColor Cyan
$autologonExe = "$TargetDir\Autologon.exe"
if (-not (Test-Path $autologonExe)) {
    try {
        $autologonZip = "$TargetDir\Autologon.zip"
        Write-Host "      Downloading official Sysinternals Autologon from Microsoft..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri "https://download.sysinternals.com/files/AutoLogon.zip" -OutFile $autologonZip -UseBasicParsing
        Expand-Archive -Path $autologonZip -DestinationPath $TargetDir -Force
        Remove-Item $autologonZip -Force
    } catch {
        Write-Error "Could not download Sysinternals Autologon from Microsoft: $_. Automatic logon cannot be securely configured without Autologon.exe. Setup aborted."
        exit 1
    }
}

if (-not (Test-Path $autologonExe)) {
    $autologon64 = "$TargetDir\Autologon64.exe"
    if (Test-Path $autologon64) {
        $autologonExe = $autologon64
    } else {
        Write-Error "Autologon.exe was not found in extracted archive. Setup aborted."
        exit 1
    }
}

# Verify Microsoft Authenticode digital signature before executing
Write-Host "      Verifying Microsoft digital signature on $autologonExe..." -ForegroundColor Cyan
$sig = Get-AuthenticodeSignature -FilePath $autologonExe
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Microsoft") {
    Write-Error "Security verification failed: Autologon.exe does not have a valid Microsoft digital signature (Status: $($sig.Status), Subject: $($sig.SignerCertificate.Subject)). Setup aborted."
    exit 1
}
Write-Host "      Verified valid Microsoft digital signature (Signed by: $($sig.SignerCertificate.Subject))." -ForegroundColor Green

Write-Host "      Running Sysinternals Autologon GUI..." -ForegroundColor Green
Write-Host "      Enter your Windows password in the Autologon dialog and click 'Enable'." -ForegroundColor Cyan
Start-Process -FilePath $autologonExe -Wait

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
