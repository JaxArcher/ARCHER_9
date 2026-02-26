# Check what processes might be using the camera
Write-Host "=== Processes that might be using the camera ==="

# Check common camera-using apps
$cameraApps = @('Teams', 'Zoom', 'Skype', 'Discord', 'obs64', 'obs32', 'chrome', 'msedge', 'firefox', 'Webex', 'slack')
foreach ($app in $cameraApps) {
    $proc = Get-Process -Name $app -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "  RUNNING: $app (PID: $($proc.Id))"
    }
}

Write-Host ""
Write-Host "=== Camera device driver info ==="
$cam = Get-PnpDevice -FriendlyName 'HD Webcam eMeet C960' -Class Camera -ErrorAction SilentlyContinue
if ($cam) {
    $cam | Format-List *

    # Get driver info
    $driver = Get-PnpDeviceProperty -InstanceId $cam.InstanceId -ErrorAction SilentlyContinue
    $driverDate = $driver | Where-Object { $_.KeyName -eq 'DEVPKEY_Device_DriverDate' }
    $driverVer = $driver | Where-Object { $_.KeyName -eq 'DEVPKEY_Device_DriverVersion' }

    Write-Host "Driver Date: $($driverDate.Data)"
    Write-Host "Driver Version: $($driverVer.Data)"
}

Write-Host ""
Write-Host "=== Try disabling/re-enabling the camera ==="
Write-Host "(This sometimes fixes DirectShow pin issues)"
