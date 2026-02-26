# Disable and re-enable the eMeet C960 to reset its DirectShow state
# Requires running as Administrator

Write-Host "=== Resetting eMeet C960 camera device ==="

$device = Get-PnpDevice -FriendlyName "HD Webcam eMeet C960" -Class Camera -ErrorAction Stop

Write-Host "Current status: $($device.Status)"
Write-Host "Disabling device..."
Disable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false -ErrorAction Stop
Start-Sleep -Seconds 2

Write-Host "Re-enabling device..."
Enable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false -ErrorAction Stop
Start-Sleep -Seconds 3

$device = Get-PnpDevice -FriendlyName "HD Webcam eMeet C960" -Class Camera -ErrorAction Stop
Write-Host "New status: $($device.Status)"
Write-Host ""
Write-Host "Device has been reset. Try running ARCHER again."
