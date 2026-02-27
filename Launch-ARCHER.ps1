# ============================================================
#  ARCHER Launcher
#  Starts: Docker services -> Ollama -> LM Studio -> ARCHER
# ============================================================
#Requires -Version 5.1

$ArcherRoot  = $PSScriptRoot
$VenvPython  = Join-Path $ArcherRoot ".venv\Scripts\python.exe"
$OllamaExe   = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
$LMStudioID  = "ai.elementlabs.lmstudio"
$DockerCompose = Join-Path $ArcherRoot "docker-compose.yml"

# ─── Console Styling ─────────────────────────────────────────
$ESC = [char]27
function Write-Header {
    Clear-Host
    Write-Host ""
    Write-Host "  $ESC[96m╔═══════════════════════════════════════════════╗$ESC[0m"
    Write-Host "  $ESC[96m║  $ESC[1;97m A R C H E R   L A U N C H E R  $ESC[0m$ESC[96m              ║$ESC[0m"
    Write-Host "  $ESC[96m║  $ESC[90mYour AI companion system starting up...      $ESC[96m║$ESC[0m"
    Write-Host "  $ESC[96m╚═══════════════════════════════════════════════╝$ESC[0m"
    Write-Host ""
}

function Write-Step {
    param([string]$Icon, [string]$Label, [string]$Colour = "Cyan")
    Write-Host "  $ESC[${Colour}m$Icon  $Label$ESC[0m"
}

function Write-Ok   { param([string]$m) Write-Host "    $ESC[92m[OK]  $m$ESC[0m" }
function Write-Skip { param([string]$m) Write-Host "    $ESC[93m[SKIP] $m$ESC[0m" }
function Write-Warn { param([string]$m) Write-Host "    $ESC[93m[WARN] $m$ESC[0m" }
function Write-Fail { param([string]$m) Write-Host "    $ESC[91m[FAIL] $m$ESC[0m" }

# ─── Helpers ─────────────────────────────────────────────────
function Wait-Port {
    param([string]$Host, [int]$Port, [int]$TimeoutSec = 30, [string]$Service = "service")
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect($Host, $Port)
            $tcp.Close()
            return $true
        } catch { Start-Sleep -Milliseconds 500 }
    }
    Write-Warn "$Service did not respond on port $Port within ${TimeoutSec}s"
    return $false
}

function Is-ProcessRunning {
    param([string]$Name)
    return ($null -ne (Get-Process -Name $Name -ErrorAction SilentlyContinue))
}

# ─── Check Docker Desktop is running ─────────────────────────
function Ensure-Docker {
    Write-Step "🐳" "Checking Docker Desktop..." "Cyan"
    if (-not (Is-ProcessRunning "Docker Desktop")) {
        Write-Warn "Docker Desktop not running — attempting to start..."
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden
        $waited = 0
        while (-not (Is-ProcessRunning "com.docker.backend") -and $waited -lt 60) {
            Start-Sleep -Seconds 2; $waited += 2
            Write-Host "    $ESC[90m... waiting for Docker engine ($waited s)$ESC[0m" -NoNewline
            Write-Host "`r" -NoNewline
        }
    }

    # Make sure docker CLI responds
    $dockerOk = $false
    for ($i = 0; $i -lt 10; $i++) {
        $r = docker info 2>$null
        if ($LASTEXITCODE -eq 0) { $dockerOk = $true; break }
        Start-Sleep -Seconds 3
    }
    if ($dockerOk) { Write-Ok "Docker engine ready" }
    else           { Write-Fail "Docker engine unreachable — is Docker Desktop installed?"; exit 1 }
}

# ─── Start Docker Compose services ───────────────────────────
function Start-DockerServices {
    Write-Step "📦" "Starting ARCHER Docker services..." "Cyan"
    Set-Location $ArcherRoot
    
    # Core services (chromadb + redis) — always start these
    docker compose -f $DockerCompose up -d chromadb redis 2>&1 | Out-Null

    if ($LASTEXITCODE -eq 0) {
        Write-Ok "ChromaDB  (port 8100) starting"
        Write-Ok "Redis     (port 6377) starting"
    } else {
        Write-Warn "docker-compose returned non-zero exit. Services may already be running."
    }

    # Wait for ChromaDB health
    $chromaOk = Wait-Port "127.0.0.1" 8100 30 "ChromaDB"
    $redisOk  = Wait-Port "127.0.0.1" 6377 20 "Redis"

    if ($chromaOk) { Write-Ok "ChromaDB  healthy" } else { Write-Warn "ChromaDB slow to start — ARCHER will retry" }
    if ($redisOk)  { Write-Ok "Redis     healthy" } else { Write-Warn "Redis slow to start — memory Layer 1 may be delayed" }
}

# ─── Start Ollama ─────────────────────────────────────────────
function Start-Ollama {
    Write-Step "🦙" "Starting Ollama..." "Cyan"

    if (Is-ProcessRunning "ollama") {
        Write-Skip "Ollama already running"
        return
    }

    if (-not (Test-Path $OllamaExe)) {
        Write-Warn "Ollama not found at: $OllamaExe"
        Write-Warn "Observer / local vision will be unavailable"
        return
    }

    Start-Process $OllamaExe -WindowStyle Minimized
    # Wait up to 15s for Ollama API port 11434
    $ok = Wait-Port "127.0.0.1" 11434 15 "Ollama"
    if ($ok) { Write-Ok "Ollama    ready (port 11434)" }
    else     { Write-Warn "Ollama starting slowly — observer will retry when ready" }
}

# ─── Start LM Studio ─────────────────────────────────────────
function Start-LMStudio {
    Write-Step "🧠" "Starting LM Studio..." "Cyan"

    # Check if already open — lmstudio runs as LM Studio.exe
    if (Is-ProcessRunning "LM Studio") {
        Write-Skip "LM Studio already running"
        return
    }

    # Launch via Windows 10/11 shell: Start-Uri with ms-launch 
    Start-Process "explorer.exe" "shell:AppsFolder\$LMStudioID!App" -WindowStyle Normal
    Start-Sleep -Seconds 3
    
    if (Is-ProcessRunning "LM Studio") {
        Write-Ok "LM Studio launched"
    } else {
        Write-Warn "Could not confirm LM Studio launched — check Start Menu"
    }
}

# ─── Launch ARCHER ────────────────────────────────────────────
function Start-ARCHER {
    Write-Step "🏹" "Launching ARCHER..." "Green"
    
    if (-not (Test-Path $VenvPython)) {
        Write-Fail "Python venv not found: $VenvPython"
        Write-Fail "Run: python -m venv .venv && .venv\Scripts\pip install -e ."
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Host ""
    Write-Host "  $ESC[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$ESC[0m"
    Write-Host "  $ESC[92m  All services started. Launching ARCHER...  $ESC[0m"
    Write-Host "  $ESC[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$ESC[0m"
    Write-Host ""

    # Launch ARCHER in this same window so logs are visible
    Set-Location $ArcherRoot
    & $VenvPython -m archer
}

# ─── MAIN ─────────────────────────────────────────────────────
Write-Header
Ensure-Docker
Write-Host ""
Start-DockerServices
Write-Host ""
Start-Ollama
Write-Host ""
Start-LMStudio
Write-Host ""
Start-ARCHER
