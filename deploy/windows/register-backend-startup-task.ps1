param(
    [string]$ProjectRoot = "D:\\OceanLabs\\Language",
    [string]$TaskName = "OceanLabsBackend",
    [Alias("Host")]
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8000,
    [string]$UserName = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($UserName)) {
    $UserName = "$env:USERDOMAIN\\$env:USERNAME"
}

$runnerScript = Join-Path $ProjectRoot "deploy\\windows\\run-backend.ps1"
if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found at: $runnerScript"
}

$taskArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`" -ProjectRoot `"$ProjectRoot`" -ListenHost `"$ListenHost`" -Port $Port"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserName
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "OceanLabs backend auto-start task" -User $UserName | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Scheduled task '$TaskName' registered for user '$UserName'." -ForegroundColor Green
Write-Host "Use this when Playwright needs interactive desktop/browser context."
