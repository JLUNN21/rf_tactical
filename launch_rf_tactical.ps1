# RF Tactical Launch Script (PowerShell)
Write-Host "========================================"
Write-Host "RF Tactical - Launch Script"
Write-Host "========================================"

$RADIOCONDA_PATH = "C:\Users\jakel\Desktop\radioconda"
$MICROMAMBA_PATH = "C:\Users\jakel\Desktop\micromamba.exe"
$PROJECT_PATH = $PSScriptRoot

$env:SOAPY_SDR_PLUGIN_PATH = "$RADIOCONDA_PATH\Library\lib\SoapySDR\modules0.8"

Write-Host ""
Write-Host "[1/3] Setting SoapySDR plugin path..."
Write-Host "      $env:SOAPY_SDR_PLUGIN_PATH"

Write-Host ""
Write-Host "[2/3] Checking environment..."

if (-not (Test-Path $MICROMAMBA_PATH)) {
    Write-Host "ERROR: micromamba not found at $MICROMAMBA_PATH" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $RADIOCONDA_PATH)) {
    Write-Host "ERROR: radioconda not found at $RADIOCONDA_PATH" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "      micromamba: OK" -ForegroundColor Green
Write-Host "      radioconda: OK" -ForegroundColor Green

Write-Host ""
Write-Host "[3/3] Launching RF Tactical..."
Write-Host ""

Set-Location $PROJECT_PATH
& $MICROMAMBA_PATH run -p $RADIOCONDA_PATH python main.py

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Application crashed or exited with error" -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
