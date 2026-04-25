$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $Root ".runlogs"
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$FrontendDir = Join-Path $Root "elysia-frontend"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating Python 3.12 virtual environment..."
    py -3.12 -m venv $VenvDir
}

Write-Host "Upgrading pip..."
& $VenvPython -m pip install --upgrade pip | Tee-Object -FilePath (Join-Path $LogDir "pip-upgrade.log")

Write-Host "Installing editable Python packages with dev dependencies..."
& $VenvPython -m pip install -e "$Root\elysia[dev]" -e "$Root\MealAgent" | Tee-Object -FilePath (Join-Path $LogDir "pip-install.log")

Write-Host "Installing frontend dependencies..."
Push-Location $FrontendDir
try {
    if (Test-Path (Join-Path $FrontendDir "package-lock.json")) {
        npm ci
    } else {
        npm install
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Development setup complete."
Write-Host "Start:  powershell -ExecutionPolicy Bypass -File scripts/start-system.ps1"
Write-Host "Status: powershell -ExecutionPolicy Bypass -File scripts/status-system.ps1"
