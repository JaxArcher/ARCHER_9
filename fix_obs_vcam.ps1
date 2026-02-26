# Unregister OBS Virtual Camera DirectShow filter
# This will make the eMeet C960 accessible to OpenCV/ffmpeg
# The OBS Virtual Camera can be re-registered later from OBS settings

Write-Host "=== Checking OBS Virtual Camera registration ==="

# Find OBS Virtual Camera DLL
$obsVcamPaths = @(
    "${env:ProgramFiles}\obs-studio\bin\64bit\obs-virtualcam-module64.dll",
    "${env:ProgramFiles(x86)}\obs-studio\bin\32bit\obs-virtualcam-module32.dll",
    "${env:ProgramFiles}\obs-studio\data\obs-plugins\win-dshow\virtualcam-module64.dll"
)

$found = $false
foreach ($path in $obsVcamPaths) {
    if (Test-Path $path) {
        Write-Host "  Found OBS VCam DLL: $path"
        $found = $true
    }
}

if (-not $found) {
    Write-Host "  OBS Virtual Camera DLL not found at standard locations."
    Write-Host "  Checking registry for CLSID..."
}

# Check registry for OBS Virtual Camera CLSID
$clsid = "{A3FCE0F5-3493-419F-958A-ABA1250EC20B}"
$regPath = "HKLM:\SOFTWARE\Classes\CLSID\$clsid"
if (Test-Path $regPath) {
    Write-Host "  OBS Virtual Camera CLSID found in registry: $clsid"
    $inproc = Get-ItemProperty -Path "$regPath\InprocServer32" -ErrorAction SilentlyContinue
    if ($inproc) {
        Write-Host "  DLL Path: $($inproc.'(default)')"
    }
} else {
    Write-Host "  OBS Virtual Camera CLSID not found in HKLM registry"
    # Check HKCU too
    $regPath2 = "HKCU:\SOFTWARE\Classes\CLSID\$clsid"
    if (Test-Path $regPath2) {
        Write-Host "  Found in HKCU instead: $regPath2"
    }
}

Write-Host ""
Write-Host "To unregister OBS Virtual Camera, run one of these as Administrator:"
Write-Host "  regsvr32 /u `"<path_to_obs_virtualcam_dll>`""
Write-Host "  OR from OBS: Tools > VirtualCam > Uninstall"
