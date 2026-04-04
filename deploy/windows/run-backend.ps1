param(
    [string]$ProjectRoot = "D:\\OceanLabs\\Language",
    [Alias("Host")]
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8000
)

$ErrorActionPreference = "Continue"

$pythonExe = Join-Path $ProjectRoot "venv\\Scripts\\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at: $pythonExe"
}

Set-Location $ProjectRoot

while ($true) {
    $started = Get-Date -Format "s"
    Write-Host "[$started] Starting backend..."

    & $pythonExe -m uvicorn backend.api_server:app --host $ListenHost --port $Port --proxy-headers --forwarded-allow-ips=*
    $exitCode = $LASTEXITCODE

    $stopped = Get-Date -Format "s"
    Write-Warning "[$stopped] Backend exited with code $exitCode. Restarting in 5 seconds..."
    Start-Sleep -Seconds 5
}
