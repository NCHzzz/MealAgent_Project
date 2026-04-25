$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $Root ".runlogs"
$PidDir = Join-Path $Root ".runpids"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $Root "elysia-frontend"
$ComposeFile = Join-Path $Root "Docker\docker-compose.yml"

New-Item -ItemType Directory -Force -Path $LogDir, $PidDir | Out-Null

function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Stop-RecordedProcess {
    param([string]$Name)
    $pidFile = Join-Path $PidDir "$Name.pid"
    if (Test-Path $pidFile) {
        $recordedPid = (Get-Content $pidFile -Raw).Trim()
        if ($recordedPid) {
            Stop-Process -Id ([int]$recordedPid) -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $VenvPython)) {
    throw "Python virtual environment not found. Run: powershell -ExecutionPolicy Bypass -File scripts/setup-dev.ps1"
}

Write-Host "Starting Docker services..."
docker compose -f $ComposeFile up -d

Write-Host "Waiting for Weaviate readiness..."
if (-not (Wait-HttpOk "http://localhost:8078/v1/.well-known/ready" 90)) {
    Write-Warning "Weaviate readiness did not return OK within timeout. Continuing; check: docker compose -f Docker\docker-compose.yml logs weaviate"
}

if (-not (Test-PortListening 8000)) {
    Stop-RecordedProcess "backend"
    Write-Host "Starting backend on http://127.0.0.1:8000 ..."
    $backend = Start-Process -FilePath $VenvPython `
        -ArgumentList @('-m','uvicorn','elysia.api.app:app','--host','127.0.0.1','--port','8000') `
        -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $LogDir "backend.out.log") `
        -RedirectStandardError (Join-Path $LogDir "backend.err.log") `
        -PassThru
    Set-Content -Path (Join-Path $PidDir "backend.pid") -Value $backend.Id
} else {
    Write-Host "Backend port 8000 is already listening; not starting another backend."
}

if (-not (Wait-HttpOk "http://127.0.0.1:8000/api/health" 90)) {
    Write-Warning "Backend health did not return OK within timeout. See .runlogs/backend.err.log"
}

if (-not (Test-PortListening 3000)) {
    Stop-RecordedProcess "frontend"
    Write-Host "Starting frontend on http://127.0.0.1:3000 ..."
    $frontend = Start-Process -FilePath "cmd.exe" `
        -ArgumentList @('/c','npm run dev -- --hostname 127.0.0.1 --port 3000') `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput (Join-Path $LogDir "frontend.out.log") `
        -RedirectStandardError (Join-Path $LogDir "frontend.err.log") `
        -PassThru
    Set-Content -Path (Join-Path $PidDir "frontend.pid") -Value $frontend.Id
} else {
    Write-Host "Frontend port 3000 is already listening; not starting another frontend."
}

if (-not (Wait-HttpOk "http://127.0.0.1:3000" 120)) {
    Write-Warning "Frontend did not return HTTP response within timeout. First compile can be slow; see .runlogs/frontend.out.log"
}

Write-Host ""
Write-Host "System startup command finished."
Write-Host "Backend:  http://127.0.0.1:8000/api/health"
Write-Host "Frontend: http://127.0.0.1:3000"
Write-Host "Logs:     .runlogs/"
Write-Host "Status:   powershell -ExecutionPolicy Bypass -File scripts/status-system.ps1"
Write-Host "Stop:     powershell -ExecutionPolicy Bypass -File scripts/stop-system.ps1"
