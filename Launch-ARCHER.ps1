# ARCHER Launcher v4
# Starts: Docker -> Ollama -> LM Studio -> ARCHER (desktop or browser-only)
# Also reports whether the always-on Observer Windows Service is running --
# informational only, this script never starts/stops/manages that service
# itself, since the whole point of it is to run independently of whether
# ARCHER's desktop app or browser session is even open (Col's call,
# 2026-09-16). See scripts\install_observer_service.ps1 to set it up.
#Requires -Version 5.1

param(
    # -WebOnly launches `archer.web_main` (no desktop GUI) instead of the
    # default `archer` (full desktop app). Use ARCHER-Web.bat to double-click
    # into this mode, or run: .\Launch-ARCHER.ps1 -WebOnly
    [switch]$WebOnly
)

$ArcherRoot = $PSScriptRoot
$VenvPython = Join-Path $ArcherRoot '.venv\Scripts\python.exe'
$OllamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
$LMStudioID = 'ai.elementlabs.lmstudio'
$DockerCompose = Join-Path $ArcherRoot 'docker-compose.yml'

# ANSI colour codes via concatenation
$E = [char]27
$CYAN = $E.ToString() + '[96m'
$WHITE = $E.ToString() + '[1;97m'
$GREY = $E.ToString() + '[90m'
$GREEN = $E.ToString() + '[92m'
$YELLOW = $E.ToString() + '[93m'
$RED = $E.ToString() + '[91m'
$RESET = $E.ToString() + '[0m'

function Show-Header {
    Clear-Host
    Write-Host ''
    Write-Host ($CYAN + '  +================================================+' + $RESET)
    Write-Host ($CYAN + '  |  ' + $WHITE + 'A R C H E R   L A U N C H E R' + $RESET + $CYAN + '               |' + $RESET)
    Write-Host ($CYAN + '  |  ' + $GREY + 'Your AI companion starting up...             ' + $CYAN + '|' + $RESET)
    Write-Host ($CYAN + '  +================================================+' + $RESET)
    Write-Host ''
}

function Show-Step { param([string]$Label) Write-Host ($CYAN + '  >> ' + $Label + $RESET) }
function Show-Ok { param([string]$m)     Write-Host ($GREEN + '    [OK]   ' + $m + $RESET) }
function Show-Skip { param([string]$m)     Write-Host ($YELLOW + '    [SKIP] ' + $m + $RESET) }
function Show-Warn { param([string]$m)     Write-Host ($YELLOW + '    [WARN] ' + $m + $RESET) }
function Show-Fail { param([string]$m)     Write-Host ($RED + '    [FAIL] ' + $m + $RESET) }

function Wait-Port {
    param([string]$Hostname, [int]$Port, [int]$TimeoutSec, [string]$Service)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect($Hostname, $Port)
            $tcp.Close()
            return $true
        }
        catch { Start-Sleep -Milliseconds 500 }
    }
    Show-Warn ($Service + ' not ready on port ' + $Port + ' after ' + $TimeoutSec + 's')
    return $false
}

function Test-IsRunning {
    param([string]$Name)
    return ($null -ne (Get-Process -Name $Name -ErrorAction SilentlyContinue))
}

# Step 1 – Observer Windows Service (status only, never managed here)
function Invoke-ObserverServiceCheck {
    Show-Step 'Step 1/5  Checking ARCHER Observer Service...'
    $svc = Get-Service -Name 'ArcherObserver' -ErrorAction SilentlyContinue
    if (-not $svc) {
        Show-Skip 'Not installed -- ambient observation will not run independently of this session.'
        Show-Skip 'Set it up once with: scripts\install_observer_service.ps1 (elevated PowerShell)'
        return
    }
    if ($svc.Status -eq 'Running') {
        Show-Ok 'Running -- ambient observation already active in the background.'
    }
    else {
        Show-Warn ('Installed but not running (status: ' + $svc.Status.ToString() + '). Start it with: nssm start ArcherObserver')
    }
}

# Step 2 – Docker Desktop
function Invoke-DockerCheck {
    Show-Step 'Step 2/5  Checking Docker Desktop...'
    if (-not (Test-IsRunning 'Docker Desktop')) {
        Show-Warn 'Docker Desktop not running. Attempting to start...'
        $dockerExe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
        if (Test-Path $dockerExe) {
            Start-Process $dockerExe -WindowStyle Hidden
        }
        else {
            Show-Fail 'Docker Desktop not found. Install from https://www.docker.com'
            Read-Host 'Press Enter to exit'; exit 1
        }
        $waited = 0
        while ($waited -lt 60) {
            Start-Sleep -Seconds 2
            $waited += 2
            $null = docker info
            if ($LASTEXITCODE -eq 0) { break }
            Write-Host ($GREY + '    ... waiting ' + $waited.ToString() + 's' + $RESET)
        }
    }
    $null = docker info
    if ($LASTEXITCODE -eq 0) { Show-Ok 'Docker engine ready' }
    else { Show-Fail 'Docker engine unreachable.'; Read-Host 'Press Enter to exit'; exit 1 }
}

# Step 3 – Docker services
function Invoke-DockerServices {
    Show-Step 'Step 3/5  Starting Docker services...'
    Set-Location $ArcherRoot
    $null = docker compose -f $DockerCompose up -d chromadb redis
    $chromaOk = Wait-Port '127.0.0.1' 8100 30 'ChromaDB'
    $redisOk = Wait-Port '127.0.0.1' 6377 20 'Redis'
    if ($chromaOk) { Show-Ok 'ChromaDB  port 8100 healthy' } else { Show-Warn 'ChromaDB slow — ARCHER will retry' }
    if ($redisOk) { Show-Ok 'Redis     port 6377 healthy' } else { Show-Warn 'Redis slow — Layer 1 memory may be delayed' }
}

# Step 4 – Ollama
function Invoke-Ollama {
    Show-Step 'Step 4/6  Starting Ollama...'
    if (Test-IsRunning 'ollama') { Show-Skip 'Ollama already running'; return }
    if (-not (Test-Path $OllamaExe)) { Show-Warn 'Ollama not found — local vision unavailable'; return }
    Start-Process $OllamaExe -WindowStyle Minimized
    $ok = Wait-Port '127.0.0.1' 11434 15 'Ollama'
    if ($ok) { Show-Ok 'Ollama    port 11434 ready' }
    else { Show-Warn 'Ollama starting slowly — Observer will retry' }
}

# Step 5 – LM Studio
function Invoke-LMStudio {
    Show-Step 'Step 5/6  Starting LM Studio...'
    if (Test-IsRunning 'LM Studio') { Show-Skip 'LM Studio already running'; return }
    Start-Process 'explorer.exe' ('shell:AppsFolder\' + $LMStudioID + '!App') -WindowStyle Normal
    Start-Sleep -Seconds 3
    if (Test-IsRunning 'LM Studio') { Show-Ok 'LM Studio launched' }
    else { Show-Warn 'LM Studio may still be loading — check taskbar' }
}

# Step 6 – barehands (bare-hand gesture control + Notes/Props board).
# Standalone stdlib-Python app, its own server on :8794 -- previously had to
# be started by hand in a separate window, which is why the GESTURE tab
# kept saying "not reachable" (2026-09-16, Col's report). Backgrounded the
# same way Docker is above; safe to call every launch since it no-ops if
# already running.
$BarehandsDir = Join-Path $ArcherRoot 'barehands'
$BarehandsBat = Join-Path $BarehandsDir 'run.bat'
function Invoke-Barehands {
    Show-Step 'Step 6/6  Starting barehands...'
    if (Wait-Port '127.0.0.1' 8794 1 'barehands') { Show-Skip 'barehands already running on :8794'; return }
    if (-not (Test-Path $BarehandsBat)) { Show-Warn 'barehands/run.bat not found — GESTURE tab will show "not reachable"'; return }
    Start-Process -FilePath $BarehandsBat -WorkingDirectory $BarehandsDir -WindowStyle Hidden
    $ok = Wait-Port '127.0.0.1' 8794 10 'barehands'
    if ($ok) { Show-Ok 'barehands  port 8794 ready' }
    else { Show-Warn 'barehands starting slowly — open the GESTURE tab in a few seconds and reload' }
}

# Auto-open the browser once the server actually answers (2026-09-16,
# Col's ask: shouldn't have to type the URL in by hand every launch).
# Runs as a background job so it doesn't block the foreground
# `& $VenvPython -m archer.web_main` call right after it -- that call
# doesn't return until ARCHER exits, so this has to poll concurrently,
# not before. Silent no-op if the server never comes up in time (the
# console output from web_main itself is the real error signal in that
# case); this job just won't open anything.
function Start-BrowserAutoOpen {
    param([string]$Url)
    Start-Job -ScriptBlock {
        param($Url)
        for ($i = 0; $i -lt 30; $i++) {
            try {
                $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
                if ($resp.StatusCode -eq 200) {
                    Start-Process $Url
                    return
                }
            } catch {
                Start-Sleep -Seconds 1
            }
        }
    } -ArgumentList $Url | Out-Null
}

# Launch ARCHER
function Invoke-ARCHER {
    param([switch]$WebOnly)
    if (-not (Test-Path $VenvPython)) {
        Show-Fail ('Python venv not found: ' + $VenvPython)
        Show-Fail 'Run: python -m venv .venv  then  .venv\Scripts\pip install -e .'
        Read-Host 'Press Enter to exit'; exit 1
    }
    Write-Host ''
    Write-Host ($GREY + '  ------------------------------------------------' + $RESET)
    if ($WebOnly) {
        Write-Host ($GREEN + '  All services ready. Launching ARCHER (browser-only)...' + $RESET)
    }
    else {
        Write-Host ($GREEN + '  All services ready. Launching ARCHER (desktop)...' + $RESET)
    }
    Write-Host ($GREY + '  ------------------------------------------------' + $RESET)
    Write-Host ''
    Set-Location $ArcherRoot
    if ($WebOnly) {
        Start-BrowserAutoOpen -Url 'http://127.0.0.1:8200/app'
        & $VenvPython -m archer.web_main
    }
    else {
        & $VenvPython -m archer
    }
}

# MAIN
Show-Header
Invoke-ObserverServiceCheck
Write-Host ''
Invoke-DockerCheck
Write-Host ''
Invoke-DockerServices
Write-Host ''
Invoke-Ollama
Write-Host ''
Invoke-LMStudio
Write-Host ''
Invoke-Barehands
Write-Host ''
Invoke-ARCHER -WebOnly:$WebOnly
