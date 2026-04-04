param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

$healthUrl = "$BaseUrl/api/health"
$response = Invoke-RestMethod -Uri $healthUrl -Method Get

Write-Host "Health response:" -ForegroundColor Cyan
$response | ConvertTo-Json -Depth 6

if ($response.status -ne "ok") {
    throw "Backend health check failed."
}

Write-Host "Backend looks healthy." -ForegroundColor Green
