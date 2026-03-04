# Fix Launch-ARCHER.ps1 line 88 in-place
$file = 'D:\ARCHER_9\Launch-ARCHER.ps1'
$content = [System.IO.File]::ReadAllText($file, [System.Text.Encoding]::UTF8)

# Replace the problematic concatenation — use a plain string with no quotes in the suffix
$old = 'Write-Host ("    " + $GREY + "... waiting for Docker engine (" + $sec + "s)" + $RESET)'
$new = 'Write-Host ("    " + $GREY + "... waiting for Docker engine (" + $sec.ToString() + "s" + ")" + $RESET)'

if ($content.Contains($old)) {
    $content = $content.Replace($old, $new)
    [System.IO.File]::WriteAllText($file, $content, [System.Text.Encoding]::UTF8)
    Write-Host "Fixed."
}
else {
    Write-Host "Pattern not found — checking encoding..."
    $lines = $content -split "`r`n"
    $line88 = $lines[87]
    Write-Host "Line 88: $line88"
    # Show character codes around 's)'
    $idx = $line88.IndexOf("s)")
    if ($idx -ge 0) {
        for ($i = [Math]::Max(0, $idx - 3); $i -lt [Math]::Min($line88.Length, $idx + 5); $i++) {
            Write-Host ("  [$i] char='" + $line88[$i] + "' code=" + [int][char]$line88[$i])
        }
    }
}
