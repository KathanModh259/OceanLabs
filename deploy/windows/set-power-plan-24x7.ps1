# Run as Administrator.
# Prevent sleep/hibernation so recorder automation can run continuously.

$ErrorActionPreference = "Stop"

powercfg /hibernate off | Out-Null
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-ac 0 | Out-Null

Write-Host "Power settings updated for 24x7 operation (AC mode)." -ForegroundColor Green
