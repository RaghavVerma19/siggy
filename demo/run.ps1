# run.ps1 — Start the Siggy demo with OTel auto-instrumentation (Windows)
#
# Usage:
#   .\run.ps1                      (uses siggy instrument if available)
#   .\run.ps1 -Manual              (skip siggy, use manual OTel env vars)
#   .\run.ps1 -NoOtel              (run Flask without any OTel)
#
# Requires: Python, Flask (see requirements.txt)

param(
    [switch]$Manual,
    [switch]$NoOtel
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "Siggy Demo App" -ForegroundColor Cyan
Write-Host "=" * 40

# Check if venv exists
$VenvPython = "..\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = "python"
}

# Try siggy instrument first
$siggyAvailable = Get-Command siggy -ErrorAction SilentlyContinue

if ($NoOtel) {
    Write-Host "Running without OTel instrumentation..." -ForegroundColor Yellow
    & $VenvPython app.py
}
elseif ($siggyAvailable -and -not $Manual) {
    Write-Host "Using siggy instrument for auto-instrumentation" -ForegroundColor Green
    & siggy instrument --service demo-api $VenvPython app.py
}
elseif ($Manual -or -not $siggyAvailable) {
    Write-Host "Using manual OTel environment variables" -ForegroundColor Yellow

    $env:OTEL_SERVICE_NAME = "demo-api"
    $env:OTEL_TRACES_EXPORTER = "otlp"
    $env:OTEL_METRICS_EXPORTER = "otlp"
    $env:OTEL_LOGS_EXPORTER = "otlp"
    $env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"
    $env:OTEL_RESOURCE_ATTRIBUTES = "service.name=demo-api,deployment.environment=development"

    # Try opentelemetry-instrument wrapper
    $otelInstrument = Get-Command opentelemetry-instrument -ErrorAction SilentlyContinue
    if ($otelInstrument) {
        & opentelemetry-instrument $VenvPython app.py
    }
    else {
        Write-Host "opentelemetry-instrument not found, running without auto-instrumentation" -ForegroundColor Yellow
        & $VenvPython app.py
    }
}
