$ErrorActionPreference = "Continue"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PidDir = Join-Path $Root ".runpids"
$ComposeFile = Join-Path $Root "Docker\docker-compose.yml"

function Stop-RecordedProcess {
    param([string]$Name)
    $pidFile = Join-Path $PidDir "$Name.pid"
    if (Test-Path $pidFile) {
        $recordedPid = (Get-Content $pidFile -Raw).Trim()
        if ($recordedPid) {
            Write-Host "Stopping $Name PID $recordedPid"
            Stop-Process -Id ([int]$recordedPid) -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "No recorded PID for $Name"
    }
}

Stop-RecordedProcess "frontend"
Stop-RecordedProcess "backend"

Write-Host "Stopping processes still listening on ports 3000/8000 if any..."
Get-NetTCPConnection -LocalPort 3000,8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

Write-Host "Stopping Docker services..."
docker compose -f $ComposeFile stop

Write-Host "Stopped frontend/backend and Docker services."
