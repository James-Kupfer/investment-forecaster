# Optionally syncs the latest Excel profile data into Postgres, then runs the
# investment-forecaster pipeline for a single stock symbol, a comma-separated
# list of symbols, or, if "pipeline" is entered, for every active position.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

# Required on Windows: without this, non-ASCII characters in LLM responses
# (em-dashes, smart quotes) get silently corrupted before being stored.
$env:PYTHONUTF8 = "1"

# 0. Sync prompt_registry from personas/*.md -- editing a persona file and
# merging it does not change agent behavior on its own (BaseAgent reads the
# active prompt from the DB, not the file), so every run self-heals any
# persona edit that was merged but never seeded via update_prompt.py.
Write-Host "Syncing prompt_registry from personas/*.md ..."
python scripts\sync_prompts.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Prompt sync reported errors (exit code $LASTEXITCODE)."
    $continueChoice = Read-Host "Continue with the forecast pipeline anyway? (1 = Yes, 2 = No)"
    if ($continueChoice -ne "1") {
        Write-Host "Aborting."
        exit 1
    }
}
Write-Host ""

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

# 2. Force?
$forceChoice = Read-Host "Force? Bypass the triage gate (1 = Yes, 2 = No)"
$force = $forceChoice -eq "1"

# 3. List stock(s):
$stockInput = Read-Host "List stock(s) (symbol, comma-separated symbols, or `"pipeline`" to run every active position)"
if ([string]::IsNullOrWhiteSpace($stockInput)) {
    Write-Host "No stock entered -- exiting."
    Read-Host "Press Enter to close"
    exit 1
}
$stockInput = $stockInput.Trim()
$runAll = $stockInput.ToLower() -eq "pipeline"
$symbolList = $stockInput.Split(",") | ForEach-Object { $_.Trim().ToUpper() } | Where-Object { $_ -ne "" }
$symbolsArg = $symbolList -join ","

if ($runAll -and $force) {
    Write-Host "Force is not supported for a full pipeline run (--force requires a single symbol) -- ignoring."
    $force = $false
}

Write-Host ""

if ($runAll) {
    Write-Host "Running pipeline for all active positions ..."
    python scripts\run_forecasts.py
    $forecastExitCode = $LASTEXITCODE

    if ($forecastExitCode -ne 0) {
        Write-Host ""
        Write-Host "Pipeline reported errors (exit code $forecastExitCode)."
    }

    exit $forecastExitCode
} elseif ($symbolList.Count -gt 1) {
    # Multiple symbols: spin off one window per symbol so they run in
    # parallel, staggering launches slightly to avoid hammering the API/DB
    # with simultaneous startups. Each window runs a small generated PS1
    # file rather than a single cmd.exe command-line string -- cmd's /K
    # quote-stripping breaks when the command contains more than one quoted
    # substring (here, the ticker and the working directory both need
    # quoting), which corrupted PYTHONUTF8 and crashed the interpreter.
    Write-Host "Launching $($symbolList.Count) parallel pipeline windows ..."
    $runTempDir = Join-Path $env:TEMP "investment-forecaster-runs"
    New-Item -ItemType Directory -Path $runTempDir -Force | Out-Null
    $i = 0
    foreach ($sym in $symbolList) {
        $i++
        $forceArg = if ($force) { "--force" } else { "" }
        $launchScript = Join-Path $runTempDir "run_$i.ps1"
        $launchScriptContent = @"
`$host.UI.RawUI.WindowTitle = "$sym"
`$env:PYTHONUTF8 = "1"
Set-Location "$RepoRoot"
python scripts\run_forecasts.py --symbol "$sym" $forceArg
Write-Host ""
Read-Host "Press Enter to close"
"@
        Set-Content -Path $launchScript -Value $launchScriptContent -Encoding UTF8
        Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$launchScript`""
        Write-Host "  Started window for $sym"
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    Write-Host "All windows launched -- check each window for its own result."
    exit 0
} else {
    Write-Host "Running pipeline for $symbolsArg ..."
    if ($force) {
        python scripts\run_forecasts.py --symbols $symbolsArg --force
    } else {
        python scripts\run_forecasts.py --symbols $symbolsArg
    }
    $forecastExitCode = $LASTEXITCODE

    if ($forecastExitCode -ne 0) {
        Write-Host ""
        Write-Host "Pipeline reported errors (exit code $forecastExitCode)."
    }

    exit $forecastExitCode
}
