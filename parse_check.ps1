$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    'D:\ARCHER_9\Launch-ARCHER.ps1',
    [ref]$tokens,
    [ref]$errors
)
Write-Host ("Parse errors found: " + $errors.Count)
foreach ($e in $errors) {
    Write-Host ("  Line " + $e.Extent.StartLineNumber + ": " + $e.Message)
}
if ($errors.Count -eq 0) { Write-Host "SYNTAX OK" }
