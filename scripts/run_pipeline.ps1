# Optionally syncs the latest Excel profile data into Postgres, then runs the
# investment-forecaster pipeline for a single stock symbol or, if "pipeline"
# is entered, for every active position.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

# Required on Windows: without this, non-ASCII characters in LLM responses
# (em-dashes, smart quotes) get silently corrupted before being stored.
$env:PYTHONUTF8 = "1"

# 1. Refresh data?
$refreshChoice = Read-Host "Refresh DB from Excel before forecasting? (1 = Yes, 2 = No)"

if ($refreshChoice -eq "1") {
    $portfolioManagerDir = Join-Path $RepoRoot "..\investment-portfolio-manager"
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
            $continueChoice = Read-Host "Continue with the forecast pipeline anyway? (1 = Yes, 2 = No)"
            if ($continueChoice -ne "1") {
                Write-Host "Aborting."
                exit 1
            }
        }
        Write-Host ""
    }
} else {
    Write-Host "Skipping DB refresh."
    Write-Host ""
}

# 2. List stock:
$stockInput = Read-Host "List stock (symbol, or `"pipeline`" to run every active position)"
if ([string]::IsNullOrWhiteSpace($stockInput)) {
    Write-Host "No stock entered -- exiting."
    Read-Host "Press Enter to close"
    exit 1
}
$stockInput = $stockInput.Trim()
$runAll = $stockInput.ToLower() -eq "pipeline"
$symbol = $stockInput.ToUpper()

# 3. Force?
$forceChoice = Read-Host "Force? Bypass the triage gate (1 = Yes, 2 = No)"
$force = $forceChoice -eq "1"

if ($runAll -and $force) {
    Write-Host "Force is not supported for a full pipeline run (--force requires a single symbol) -- ignoring."
    $force = $false
}

Write-Host ""

if ($runAll) {
    Write-Host "Running pipeline for all active positions ..."
    python scripts\run_forecasts.py
} else {
    Write-Host "Running pipeline for $symbol ..."
    if ($force) {
        python scripts\run_forecasts.py --symbol $symbol --force
    } else {
        python scripts\run_forecasts.py --symbol $symbol
    }
}
$forecastExitCode = $LASTEXITCODE

if ($forecastExitCode -ne 0) {
    Write-Host ""
    Write-Host "Pipeline reported errors (exit code $forecastExitCode)."
}

exit $forecastExitCode
