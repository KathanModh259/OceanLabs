param(
    [string]$ProjectRoot = "D:\\OceanLabs\\Language",
    [string]$ServiceName = "OceanLabsBackend",
    [Alias("Host")]
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8000,
    [string]$NssmPath = "nssm"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command $NssmPath -ErrorAction SilentlyContinue)) {
    throw "NSSM was not found. Install NSSM and add it to PATH, or pass -NssmPath <full-path>."
}

$pythonExe = Join-Path $ProjectRoot "venv\\Scripts\\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at: $pythonExe"
}

$logsDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$appArgs = "-m uvicorn backend.api_server:app --host $ListenHost --port $Port --proxy-headers --forwarded-allow-ips=*"

$serviceExists = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $serviceExists) {
    & $NssmPath install $ServiceName $pythonExe $appArgs | Out-Null
}

& $NssmPath set $ServiceName Application $pythonExe | Out-Null
& $NssmPath set $ServiceName AppParameters $appArgs | Out-Null
& $NssmPath set $ServiceName AppDirectory $ProjectRoot | Out-Null
& $NssmPath set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $NssmPath set $ServiceName AppStdout (Join-Path $logsDir "backend.stdout.log") | Out-Null
& $NssmPath set $ServiceName AppStderr (Join-Path $logsDir "backend.stderr.log") | Out-Null
& $NssmPath set $ServiceName AppRotateFiles 1 | Out-Null
& $NssmPath set $ServiceName AppRotateOnline 1 | Out-Null
& $NssmPath set $ServiceName AppRotateBytes 10485760 | Out-Null
& $NssmPath set $ServiceName AppEnvironmentExtra "PYTHONUNBUFFERED=1" | Out-Null

try {
    & $NssmPath restart $ServiceName | Out-Null
} catch {
    & $NssmPath start $ServiceName | Out-Null
}

Write-Host "Service '$ServiceName' is installed and running." -ForegroundColor Green
Write-Host "Health check: http://127.0.0.1:$Port/api/health"
