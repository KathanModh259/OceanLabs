param(
    [string]$ServiceName = "OceanLabsBackend",
    [string]$NssmPath = "nssm"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command $NssmPath -ErrorAction SilentlyContinue)) {
    throw "NSSM was not found. Install NSSM and add it to PATH, or pass -NssmPath <full-path>."
}

$serviceExists = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $serviceExists) {
    Write-Host "Service '$ServiceName' is not installed." -ForegroundColor Yellow
    exit 0
}

try {
    & $NssmPath stop $ServiceName | Out-Null
} catch {
    Write-Host "Service '$ServiceName' was not running." -ForegroundColor Yellow
}

& $NssmPath remove $ServiceName confirm | Out-Null
Write-Host "Service '$ServiceName' removed." -ForegroundColor Green
