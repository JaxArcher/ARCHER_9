# ARCHER Launcher v3
# Starts: Docker -> Ollama -> LM Studio -> ARCHER
#Requires -Version 5.1

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

# Step 1 – Docker Desktop
function Invoke-DockerCheck {
    Show-Step 'Step 1/4  Checking Docker Desktop...'
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

# Step 2 – Docker services
function Invoke-DockerServices {
    Show-Step 'Step 2/4  Starting Docker services...'
    Set-Location $ArcherRoot
    $null = docker compose -f $DockerCompose up -d chromadb redis
    $chromaOk = Wait-Port '127.0.0.1' 8100 30 'ChromaDB'
    $redisOk = Wait-Port '127.0.0.1' 6377 20 'Redis'
    if ($chromaOk) { Show-Ok 'ChromaDB  port 8100 healthy' } else { Show-Warn 'ChromaDB slow — ARCHER will retry' }
    if ($redisOk) { Show-Ok 'Redis     port 6377 healthy' } else { Show-Warn 'Redis slow — Layer 1 memory may be delayed' }
}

# Step 3 – Ollama
function Invoke-Ollama {
    Show-Step 'Step 3/4  Starting Ollama...'
    if (Test-IsRunning 'ollama') { Show-Skip 'Ollama already running'; return }
    if (-not (Test-Path $OllamaExe)) { Show-Warn 'Ollama not found — local vision unavailable'; return }
    Start-Process $OllamaExe -WindowStyle Minimized
    $ok = Wait-Port '127.0.0.1' 11434 15 'Ollama'
    if ($ok) { Show-Ok 'Ollama    port 11434 ready' }
    else { Show-Warn 'Ollama starting slowly — Observer will retry' }
}

# Step 4 – LM Studio
function Invoke-LMStudio {
    Show-Step 'Step 4/4  Starting LM Studio...'
    if (Test-IsRunning 'LM Studio') { Show-Skip 'LM Studio already running'; return }
    Start-Process 'explorer.exe' ('shell:AppsFolder\' + $LMStudioID + '!App') -WindowStyle Normal
    Start-Sleep -Seconds 3
    if (Test-IsRunning 'LM Studio') { Show-Ok 'LM Studio launched' }
    else { Show-Warn 'LM Studio may still be loading — check taskbar' }
}

# Launch ARCHER
function Invoke-ARCHER {
    if (-not (Test-Path $VenvPython)) {
        Show-Fail ('Python venv not found: ' + $VenvPython)
        Show-Fail 'Run: python -m venv .venv  then  .venv\Scripts\pip install -e .'
        Read-Host 'Press Enter to exit'; exit 1
    }
    Write-Host ''
    Write-Host ($GREY + '  ------------------------------------------------' + $RESET)
    Write-Host ($GREEN + '  All services ready. Launching ARCHER...        ' + $RESET)
    Write-Host ($GREY + '  ------------------------------------------------' + $RESET)
    Write-Host ''
    Set-Location $ArcherRoot
    & $VenvPython -m archer
}

# MAIN
Show-Header
Invoke-DockerCheck
Write-Host ''
Invoke-DockerServices
Write-Host ''
Invoke-Ollama
Write-Host ''
Invoke-LMStudio
Write-Host ''
Invoke-ARCHER
