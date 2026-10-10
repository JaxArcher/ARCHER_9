# Repairs the main Ollama install so ARCHER's brain model (gemma4) runs on
# the graphics card again, and stops the same break from happening again.
# Written 2026-10-08.
#
# What went wrong (from Ollama's own logs):
#   - 2026-10-07 08:26: the Ollama tray app tried to auto-update itself.
#     It couldn't replace ollama.exe because ArcherObserverOllama (the
#     observer's CPU-only Ollama, a Windows service running as SYSTEM) was
#     running that same file. The installer gave up and rolled back.
#   - The rollback left the install half-old, half-new and without its GPU
#     files (lib\ollama has no cuda folder any more). Since the next start,
#     Ollama only finds the CPU ("inference compute ... library=cpu"), so
#     gemma4 loads into regular memory with nothing on the graphics card.
#
# What this script does, in order:
#   1. Stops ARCHER's two observer services, so nothing holds Ollama's files.
#   2. Closes the Ollama tray app and any Ollama processes.
#   3. Reinstalls Ollama from the official installer the tray app already
#      downloaded (its digital signature is checked first). Your models,
#      settings and environment variables are not touched.
#   4. Starts the Ollama tray app again as you (not as Administrator).
#   5. Loads ARCHER's main model and reports how much of it is on the GPU.
#   6. Re-registers the observer services with their own separate copy of
#      Ollama (install_observer_service.ps1), so future Ollama updates
#      can't collide with them.
#
# Before running: close ARCHER (the browser tab and its window).
# Run from an elevated (Administrator) PowerShell, signed in as yourself:
#   cd D:\ARCHER_9
#   .\scripts\repair_ollama_gpu.ps1
# If no downloaded installer is found, get OllamaSetup.exe from
# https://ollama.com/download and run:
#   .\scripts\repair_ollama_gpu.ps1 -Installer "C:\path\to\OllamaSetup.exe"

param(
    [string]$Installer = "",
    [string]$MainModel = "gemma4:e4b-it-qat"
)

$ErrorActionPreference = "Stop"

$ArcherRoot   = "D:\ARCHER_9"
$LogDir       = Join-Path $ArcherRoot "logs"
$MainHost     = "127.0.0.1:11434"
$OllamaDir    = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
$OllamaLibDir = Join-Path $OllamaDir "lib\ollama"
$AppExe       = Join-Path $OllamaDir "ollama app.exe"
$ServerLog    = Join-Path $env:LOCALAPPDATA "Ollama\server.log"
$ProcNames    = @("ollama app", "ollama", "llama-server")
# Stop order matters: the observer depends on its Ollama service.
$ObserverServices = @("ArcherObserver", "ArcherObserverOllama")

function Stop-WithError([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text" -ForegroundColor Cyan
}

function Test-MainOllama {
    try {
        return (Invoke-RestMethod -Uri "http://$MainHost/api/version" -TimeoutSec 2)
    }
    catch {
        return $null
    }
}

# ---------------------------------------------------------------- checks
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Stop-WithError "Run this from an elevated (Administrator) PowerShell."
}
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Stop-WithError "nssm not found on PATH. It's needed to re-register the observer services: winget install nssm (then reopen this terminal)."
}
$ObserverInstallScript = Join-Path $PSScriptRoot "install_observer_service.ps1"
if (-not (Test-Path $ObserverInstallScript)) {
    Stop-WithError "Can't find $ObserverInstallScript."
}

if (-not $Installer) {
    $updatesDir = Join-Path $env:LOCALAPPDATA "Ollama\updates_v2"
    $found = Get-ChildItem -Path $updatesDir -Filter "OllamaSetup.exe" -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $Installer = $found.FullName }
}
if (-not $Installer -or -not (Test-Path $Installer)) {
    Stop-WithError "No Ollama installer found. Download OllamaSetup.exe from https://ollama.com/download, then re-run with -Installer `"<path to OllamaSetup.exe>`"."
}
$sig = Get-AuthenticodeSignature -FilePath $Installer
$signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "(none)" }
if ($sig.Status -ne "Valid" -or $signer -notmatch "Ollama") {
    Stop-WithError "The installer at $Installer isn't validly signed by Ollama (status: $($sig.Status), signer: $signer). Not running it. Download a fresh copy from https://ollama.com/download and re-run with -Installer."
}
Write-Host "Installer: $Installer"
Write-Host "Signed by: $signer"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ------------------------------------------ 1. stop the observer services
Write-Step "1/6  Stopping ARCHER's observer services"
foreach ($svc in $ObserverServices) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s -and $s.Status -ne "Stopped") {
        Write-Host "Stopping $svc..."
        Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
        try {
            $s.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
        }
        catch {
            Stop-WithError "$svc didn't stop within 30 seconds. Restart the PC, then run this script again before opening ARCHER."
        }
    }
    elseif ($s) {
        Write-Host "$svc is already stopped."
    }
    else {
        Write-Host "$svc isn't installed (it will be set up in step 6)."
    }
}

# ------------------------------------------------ 2. close Ollama itself
Write-Step "2/6  Closing Ollama"
Get-Process -Name $ProcNames -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$left = @(Get-Process -Name $ProcNames -ErrorAction SilentlyContinue)
if ($left.Count -gt 0) {
    $list = ($left | ForEach-Object { "$($_.ProcessName) (PID $($_.Id))" }) -join ", "
    Stop-WithError "These are still running: $list. Close them or restart the PC, then re-run."
}
Write-Host "Ollama is closed."

# ------------------------------------------------- 3. reinstall Ollama
Write-Step "3/6  Reinstalling Ollama (this can take a few minutes)"
$installLog = Join-Path $LogDir "ollama_reinstall.log"
# Wait for the installer process only. Start-Process -Wait would also wait
# for everything the installer launches -- including the Ollama tray app it
# starts at the end, which never exits -- and the script would hang here
# (it did on 2026-10-08).
$proc = Start-Process -FilePath $Installer -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/LOG=`"$installLog`"") -PassThru
$proc.WaitForExit()
if ($proc.ExitCode -ne 0) {
    Stop-WithError "The installer exited with code $($proc.ExitCode). Details: $installLog"
}
$gpuDirs = @(Get-ChildItem -Path $OllamaLibDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "cuda*" })
if ($gpuDirs.Count -eq 0) {
    Stop-WithError "The installer finished, but there's still no CUDA folder in $OllamaLibDir. Details: $installLog"
}
Write-Host "Installed. GPU files present: $(($gpuDirs | ForEach-Object { $_.Name }) -join ', ')"

# --------------------------------------- 4. start the tray app, as you
Write-Step "4/6  Starting Ollama again"
# The installer may have started the tray app itself -- as Administrator,
# because this window is elevated. Close that and start it through
# Explorer instead, which runs it as your normal (non-admin) self.
Start-Sleep -Seconds 3
Get-Process -Name $ProcNames -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
if (-not (Test-Path $AppExe)) {
    Stop-WithError "Can't find $AppExe after the reinstall. Details: $installLog"
}
Start-Process -FilePath "explorer.exe" -ArgumentList "`"$AppExe`""

$version = $null
for ($i = 0; $i -lt 60; $i++) {
    $version = Test-MainOllama
    if ($version) { break }
    Start-Sleep -Seconds 1
}
if (-not $version) {
    Stop-WithError "Ollama didn't start answering on $MainHost within 60 seconds. Start Ollama from the Start menu, then re-run this script."
}
Write-Host "Ollama $($version.version) is up on $MainHost."

# ----------------------------------------- 5. is the brain on the GPU?
Write-Step "5/6  Loading $MainModel and checking where it lands"
# num_ctx 4096 matches the context ARCHER's own chat requests use.
$body = @{ model = $MainModel; options = @{ num_ctx = 4096 } } | ConvertTo-Json -Depth 4
try {
    Invoke-RestMethod -Method Post -Uri "http://$MainHost/api/generate" -Body $body -ContentType "application/json" -TimeoutSec 300 | Out-Null
}
catch {
    Write-Warning "Loading $MainModel failed: $($_.Exception.Message)"
}
$gpuPct = $null
try {
    $ps = Invoke-RestMethod -Uri "http://$MainHost/api/ps" -TimeoutSec 10
    $m = $ps.models | Where-Object { $_.name -eq $MainModel -or $_.model -eq $MainModel } | Select-Object -First 1
    if ($m -and $m.size -gt 0) {
        $gpuPct = [math]::Round(100 * $m.size_vram / $m.size)
        $sizeGb = [math]::Round($m.size / 1GB, 1)
        Write-Host "$MainModel is loaded: $sizeGb GB, $gpuPct% on the GPU."
    }
    else {
        Write-Warning "$MainModel doesn't show as loaded. Is it pulled? (ollama list)"
    }
}
catch {
    Write-Warning "Couldn't ask Ollama what's loaded: $($_.Exception.Message)"
}
if (Test-Path $ServerLog) {
    $compute = Select-String -Path $ServerLog -Pattern "inference compute" | Select-Object -Last 1
    if ($compute) { Write-Host "Ollama sees: $($compute.Line)" }
}

# ------------------------- 6. observer services, with their own Ollama
Write-Step "6/6  Re-registering the observer services with their own copy of Ollama"
try {
    & $ObserverInstallScript
}
catch {
    Stop-WithError "Re-registering the observer services failed: $($_.Exception.Message). Ollama itself is repaired; re-run .\scripts\install_observer_service.ps1 once the problem is fixed."
}
# That script ends with exit 1 on its own errors, and with a successful
# nssm start (exit code 0) when everything worked.
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Re-registering the observer services stopped with an error (see above). Ollama itself is repaired; re-run .\scripts\install_observer_service.ps1 once the problem is fixed."
}

# ---------------------------------------------------------------- summary
Write-Host ""
if ($gpuPct -ne $null -and $gpuPct -ge 90) {
    Write-Host "REPAIRED: $MainModel is on the graphics card ($gpuPct%)." -ForegroundColor Green
}
elseif ($gpuPct -ne $null -and $gpuPct -gt 0) {
    Write-Host "PARTLY: $MainModel is only $gpuPct% on the graphics card. Something else may be using a lot of video memory." -ForegroundColor Yellow
}
else {
    Write-Host "NOT YET: $MainModel still isn't on the graphics card. Send Claude this window's output." -ForegroundColor Yellow
}
Write-Host "You can open ARCHER again now."
