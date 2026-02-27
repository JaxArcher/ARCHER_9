$ArcherRoot = "D:\ARCHER_9"
$BatFile = Join-Path $ArcherRoot "ARCHER.bat"
$IconFile = Join-Path $ArcherRoot "src\archer\gui\assets\archer_icon.ico"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shortcut = Join-Path $Desktop "ARCHER.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$sc = $WshShell.CreateShortcut($Shortcut)
$sc.TargetPath = $BatFile
$sc.WorkingDirectory = $ArcherRoot
$sc.Description = "Launch ARCHER AI Companion"
$sc.WindowStyle = 1  # Normal window

# Use ARCHER icon if it exists, otherwise use a nice default
if (Test-Path $IconFile) {
    $sc.IconLocation = $IconFile
}
else {
    # Use PowerShell icon as fallback
    $sc.IconLocation = "C:\Windows\System32\shell32.dll,41"
}

$sc.Save()
Write-Host "Desktop shortcut created: $Shortcut"
