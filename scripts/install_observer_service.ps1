# Installs ARCHER's always-on observer as two auto-starting Windows
# Services via NSSM, so ambient observation runs from PC boot -- before
# anyone logs in, and independent of the desktop app or browser client
# (Col's call, 2026-09-16):
#
#   1. ArcherObserverOllama -- a CPU-only Ollama server on 127.0.0.1:11435
#      that hosts the observer's vision model (moondream). Added
#      2026-10-06: the observer service used to try launching this itself,
#      but a service runs under the SYSTEM account, which can't see Col's
#      per-user Ollama install or his models folder -- so it never came up
#      at boot, and scene analysis only worked after ARCHER was opened by
#      hand.
#   2. ArcherObserver -- `python -m archer.observer_service`, run from the
#      project root (D:\ARCHER_9) so it shares ARCHER's database, logs and
#      face snapshots. Set to depend on ArcherObserverOllama, so Windows
#      always starts Ollama first.
#
# The main GPU Ollama (127.0.0.1:11434, gemma4) is NOT touched -- it stays
# with the Ollama tray app, which starts it at login.
#
# One-time setup. Safe to re-run: both services are removed and
# re-registered cleanly each time.
#
# Prerequisites:
#   1. NSSM on PATH:  winget install nssm  (then reopen the terminal)
#   2. Ollama installed, with the observer model pulled:  ollama pull moondream
#   3. Run from an elevated (Administrator) PowerShell while signed in as
#      the user Ollama is installed for -- this script reads that user's
#      Ollama install path and models folder and writes them into the
#      service, since the service itself runs as SYSTEM and can't look
#      them up.
#
# To undo: run uninstall_observer_service.ps1.

$ErrorActionPreference = "Stop"

$ArcherRoot         = "D:\ARCHER_9"
$LogDir             = Join-Path $ArcherRoot "logs"
$ServiceName        = "ArcherObserver"
$OllamaServiceName  = "ArcherObserverOllama"
$ObserverOllamaHost = "127.0.0.1:11435"
$ObserverPort       = 11435
$ObserverModel      = "moondream"

function Stop-WithError([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

# NSSM prints some ordinary status messages on stderr. Under
# $ErrorActionPreference = "Stop", Windows PowerShell 5.1 can turn those
# into terminating errors, so run it with "Continue" and judge success by
# its exit code instead.
function Invoke-Nssm {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & nssm @args 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
    }
    foreach ($line in $out) {
        $text = "$line".Replace("`0", "").Trim()
        if ($text) { Write-Host "    $text" }
    }
    return $code
}

function Invoke-NssmChecked {
    $code = Invoke-Nssm @args
    if ($code -ne 0) {
        throw "nssm $($args -join ' ') failed (exit code $code)."
    }
}

function Remove-ServiceIfPresent([string]$Name) {
    if (Get-Service -Name $Name -ErrorAction SilentlyContinue) {
        Write-Host "Existing '$Name' service found -- removing it first so this run is clean..."
        $null = Invoke-Nssm stop $Name
        $null = Invoke-Nssm remove $Name confirm
        Start-Sleep -Seconds 2
    }
}

# ---------------------------------------------------------------- checks
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Stop-WithError "Run this from an elevated (Administrator) PowerShell."
}

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Stop-WithError "nssm not found on PATH. Install it first: winget install nssm (then reopen this terminal)."
}

$PythonExe = Join-Path $ArcherRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Stop-WithError "Venv python not found at $PythonExe. Run: python -m venv .venv  then  .venv\Scripts\pip install -e ."
}

# Ollama itself, as the signed-in user sees it.
$OllamaExe = $null
$cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cmd) { $OllamaExe = $cmd.Source }
if (-not $OllamaExe -and $env:LOCALAPPDATA) {
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $candidate) { $OllamaExe = $candidate }
}
if (-not $OllamaExe) {
    Stop-WithError "Couldn't find ollama.exe on PATH or under $env:LOCALAPPDATA\Programs\Ollama. Install Ollama, then re-run."
}

# The models folder, as the signed-in user sees it.
$ModelsDir = $env:OLLAMA_MODELS
if (-not $ModelsDir) { $ModelsDir = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User") }
if (-not $ModelsDir) { $ModelsDir = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "Machine") }
if (-not $ModelsDir) { $ModelsDir = Join-Path $env:USERPROFILE ".ollama\models" }
if (-not (Test-Path $ModelsDir)) {
    Stop-WithError "Ollama models folder not found at $ModelsDir. Set OLLAMA_MODELS to your models folder, then re-run."
}
$ModelManifest = Join-Path $ModelsDir "manifests\registry.ollama.ai\library\$ObserverModel"
if (-not (Test-Path $ModelManifest)) {
    Write-Warning "'$ObserverModel' doesn't appear to be pulled into $ModelsDir yet. Run: ollama pull $ObserverModel"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# --------------------------------------------- clear out old registrations
# Observer first -- it depends on the Ollama service.
Remove-ServiceIfPresent $ServiceName
Remove-ServiceIfPresent $OllamaServiceName

# If ARCHER itself started an observer Ollama on this port earlier this
# session, it holds the port the new service needs.
$listener = Get-NetTCPConnection -LocalPort $ObserverPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.ProcessName -eq "ollama") {
        Write-Host "An Ollama started by ARCHER is using port $ObserverPort (PID $($owner.Id)) -- stopping it so the service can take the port..."
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($owner.Id)" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $owner.Id -Force
        Start-Sleep -Seconds 2
    }
    else {
        $ownerName = if ($owner) { $owner.ProcessName } else { "unknown" }
        Stop-WithError "Port $ObserverPort is in use by '$ownerName' (PID $($listener.OwningProcess)). Free it, then re-run."
    }
}

# ------------------------------------------- 1. CPU-only observer Ollama
Write-Host ""
Write-Host "Installing '$OllamaServiceName' (CPU-only Ollama for the observer)..."
Write-Host "  Ollama:  $OllamaExe"
Write-Host "  Models:  $ModelsDir"
Write-Host "  Address: $ObserverOllamaHost"

Invoke-NssmChecked install $OllamaServiceName $OllamaExe serve
Invoke-NssmChecked set $OllamaServiceName AppDirectory (Split-Path $OllamaExe -Parent)
# CPU only, by construction: hide both CUDA and Vulkan devices from this
# server (with CUDA hidden alone, Ollama still discovered the RTX 5080
# through Vulkan). The per-request num_gpu: 0 in analyzers.py stays as a
# second guard. OLLAMA_KEEP_ALIVE=-1 keeps moondream loaded (about 1.2 GB of
# RAM) instead of unloading after 5 idle minutes and reloading on the next
# analysis.
Invoke-NssmChecked set $OllamaServiceName AppEnvironmentExtra "OLLAMA_HOST=$ObserverOllamaHost" "OLLAMA_MODELS=$ModelsDir" "CUDA_VISIBLE_DEVICES=-1" "GGML_VK_VISIBLE_DEVICES=-1" "OLLAMA_KEEP_ALIVE=-1"
Invoke-NssmChecked set $OllamaServiceName AppStdout (Join-Path $LogDir "ollama_observer.log")
Invoke-NssmChecked set $OllamaServiceName AppStderr (Join-Path $LogDir "ollama_observer.log")
Invoke-NssmChecked set $OllamaServiceName AppRotateFiles 1
Invoke-NssmChecked set $OllamaServiceName AppRotateBytes 10485760
Invoke-NssmChecked set $OllamaServiceName Start SERVICE_AUTO_START
Invoke-NssmChecked set $OllamaServiceName DisplayName "ARCHER Observer Ollama (CPU)"
Invoke-NssmChecked set $OllamaServiceName Description "CPU-only Ollama on 127.0.0.1:11435 serving the ARCHER observer's vision model (moondream). Starts at boot, before ArcherObserver."

Write-Host "Starting '$OllamaServiceName'..."
Invoke-NssmChecked start $OllamaServiceName

$ollamaUp = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-RestMethod -Uri "http://$ObserverOllamaHost/api/version" -TimeoutSec 2 | Out-Null
        $ollamaUp = $true
        break
    }
    catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ollamaUp) {
    Write-Warning "'$OllamaServiceName' started but isn't answering on $ObserverOllamaHost yet. Check $LogDir\ollama_observer.log."
}
else {
    $names = @()
    try {
        $names = @((Invoke-RestMethod -Uri "http://$ObserverOllamaHost/api/tags" -TimeoutSec 5).models | ForEach-Object { $_.name })
    }
    catch { }
    if ($names | Where-Object { $_ -eq $ObserverModel -or $_ -like "$($ObserverModel):*" }) {
        Write-Host "  OK: the service is up and can see '$ObserverModel'."
    }
    else {
        Write-Warning "The service is up but can't see '$ObserverModel' in $ModelsDir. Models it can see: $($names -join ', ')"
    }
}

# ------------------------------------------------- 2. the observer itself
Write-Host ""
Write-Host "Installing '$ServiceName'..."
Write-Host "  Python:  $PythonExe"
Write-Host "  Command: -m archer.observer_service"
Write-Host "  Workdir: $ArcherRoot"
Write-Host "  Depends: $OllamaServiceName"

Invoke-NssmChecked install $ServiceName $PythonExe "-m archer.observer_service"
# Project root, not src\ (2026-10-06): ARCHER's paths (data\archer.db,
# logs\, data\snapshots\) are relative to the working directory. Running
# from src\ silently gave the observer its own separate database, so
# nothing it saw reached ARCHER and it never had Col's face enrollment.
Invoke-NssmChecked set $ServiceName AppDirectory $ArcherRoot
Invoke-NssmChecked set $ServiceName DependOnService $OllamaServiceName
Invoke-NssmChecked set $ServiceName AppStdout (Join-Path $LogDir "observer_service_stdout.log")
Invoke-NssmChecked set $ServiceName AppStderr (Join-Path $LogDir "observer_service_stderr.log")
Invoke-NssmChecked set $ServiceName AppRotateFiles 1
Invoke-NssmChecked set $ServiceName AppRotateBytes 10485760
Invoke-NssmChecked set $ServiceName Start SERVICE_AUTO_START
Invoke-NssmChecked set $ServiceName DisplayName "ARCHER Observer Service"
Invoke-NssmChecked set $ServiceName Description "Always-on ambient observation for ARCHER (camera scene/person analysis + neglect detection). Starts at boot after ArcherObserverOllama; independent of the ARCHER desktop app / browser client."

# Works around a real, repeatedly-observed crash (2026-09-21, Col's report
# "whenever I put my PC in sleep mode it restarts at some point" -- turned
# out to be true): some of ARCHER's dependencies (numpy/scipy, pulled in
# transitively by PyTorch/InsightFace) are built against Intel's MKL/
# Fortran runtime, which installs its own console-control-event handler.
# Running as a Windows Service means no visible console, but Windows still
# broadcasts console-close-type signals on sleep, resume, logoff, and some
# shutdown paths -- and that runtime's handler responds by hard-aborting
# the whole process ("forrtl: error (200): program aborting due to
# window-CLOSE event"), confirmed live via matching crashes in
# observer_service_stderr-*.log clustered overnight. NSSM's default
# restart-on-exit policy was already masking this (service comes back
# within moments), but every occurrence still meant a cold restart --
# camera reopen, model re-warm, and a gap in ambient observation. This env
# var tells that runtime to stop installing its own handler, so a sleep/
# resume cycle no longer kills the process at all.
Invoke-NssmChecked set $ServiceName AppEnvironmentExtra "FOR_DISABLE_CONSOLE_CTRL_HANDLER=1"

Write-Host "Starting '$ServiceName'..."
Invoke-NssmChecked start $ServiceName

Write-Host ""
Write-Host "Done. Both services now start automatically at boot, Ollama first."
Write-Host "Check status:  nssm status $OllamaServiceName ; nssm status $ServiceName"
Write-Host "Observer log:  $LogDir\observer_$(Get-Date -Format yyyy-MM-dd).log"
Write-Host "Ollama log:    $LogDir\ollama_observer.log"
Write-Host "Remove both:   .\uninstall_observer_service.ps1"
