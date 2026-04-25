$ErrorActionPreference = "Continue"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$ComposeFile = Join-Path $Root "Docker\docker-compose.yml"

function Show-Port {
    param([int]$Port, [string]$Name)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($connections) {
        foreach ($connection in $connections) {
            Write-Host "$Name listening on port $Port (PID $($connection.OwningProcess))"
        }
    } else {
        Write-Host "$Name is NOT listening on port $Port"
    }
}

function Show-Http {
    param([string]$Name, [string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        Write-Host "$Name HTTP $($response.StatusCode): $Url"
    } catch {
        Write-Host "$Name HTTP check failed: $Url"
        Write-Host "  $($_.Exception.Message)"
    }
}

Write-Host "Docker services:"
docker compose -f $ComposeFile ps
Write-Host ""

Show-Port 8078 "Weaviate REST"
Show-Port 50051 "Weaviate gRPC"
Show-Port 8000 "Backend"
Show-Port 3000 "Frontend"
Write-Host ""

Show-Http "Weaviate" "http://localhost:8078/v1/.well-known/ready"
Show-Http "Backend" "http://127.0.0.1:8000/api/health"
Show-Http "Frontend" "http://127.0.0.1:3000"

Write-Host ""
Write-Host "Logs are in .runlogs/"
