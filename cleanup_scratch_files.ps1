# PowerShell script to clean up temporary scratch files in the scratch directory

$scratchDir = Join-Path $PSScriptRoot "scratch"

if (-not (Test-Path $scratchDir)) {
    Write-Host "Scratch directory '$scratchDir' does not exist." -ForegroundColor Yellow
    exit 0
}

Write-Host "Scanning '$scratchDir' for temporary scratch files..." -ForegroundColor Cyan

# Files to remove: temporary .wav audio captures, TTS chunks, stage files
$filesToDelete = Get-ChildItem -Path $scratchDir -Recurse -File | Where-Object {
    $_.Extension -eq ".wav" -or
    $_.Name -like "raw_chatterbox_response_*" -or
    $_.Name -like "last_hardware_playback_*" -or
    $_.Name -like "stage*.wav"
}

if ($filesToDelete.Count -eq 0) {
    Write-Host "No scratch files found to clean up." -ForegroundColor Green
    exit 0
}

$totalBytes = 0
foreach ($file in $filesToDelete) {
    $totalBytes += $file.Length
}

$totalMB = [math]::Round($totalBytes / 1MB, 2)
$count = $filesToDelete.Count

Write-Host "Found $count temporary scratch file(s) totaling $totalMB MB." -ForegroundColor Yellow

foreach ($file in $filesToDelete) {
    try {
        Remove-Item -Path $file.FullName -Force
    } catch {
        Write-Host "Failed to remove file: $($file.FullName) - $_" -ForegroundColor Red
    }
}

Write-Host "Cleanup complete! Removed $count file(s) ($totalMB MB freed)." -ForegroundColor Green
