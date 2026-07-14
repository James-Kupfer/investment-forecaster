# Prompts for a stock symbol, syncs the latest Excel profile data into Postgres,
# then runs the investment-forecaster pipeline for that symbol.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$symbol = Read-Host "Enter stock symbol"
if ([string]::IsNullOrWhiteSpace($symbol)) {
    Write-Host "No symbol entered -- exiting."
    Read-Host "Press Enter to close"
    exit 1
}
$symbol = $symbol.Trim().ToUpper()

# Required on Windows: without this, non-ASCII characters in LLM responses
# (em-dashes, smart quotes) get silently corrupted before being stored.
$env:PYTHONUTF8 = "1"

$portfolioManagerDir = Join-Path $PSScriptRoot "..\investment-portfolio-manager"
if (-not (Test-Path $portfolioManagerDir)) {
    Write-Host "Could not find investment-portfolio-manager at $portfolioManagerDir -- skipping sync."
} else {
    Write-Host "Syncing Excel workbook -> Postgres positions table..."
    Push-Location $portfolioManagerDir
    python scripts\run_sync.py
    $syncExitCode = $LASTEXITCODE
    Pop-Location

    if ($syncExitCode -ne 0) {
        Write-Host ""
        Write-Host "Sync reported errors (exit code $syncExitCode)."
        $continue = Read-Host "Continue with the forecast pipeline anyway? (y/N)"
        if ($continue -ne "y" -and $continue -ne "Y") {
            Write-Host "Aborting."
            Read-Host "Press Enter to close"
            exit 1
        }
    }
    Write-Host ""
}

Write-Host "Running pipeline for $symbol ..."
Write-Host ""
python scripts\run_forecasts.py --symbol $symbol

Write-Host ""
Read-Host "Done. Press Enter to close"
