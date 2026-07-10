# investment-forecaster setup script
# Reads Postgres credentials from C:\Users\james\GitHub\Secrets\postgres.py
# Run from the repo root:  .\setup\setup.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path $PSScriptRoot -Parent
$SecretsFile = "C:\Users\james\GitHub\Secrets\postgres.py"
$EnvFile   = Join-Path $RepoRoot ".env"
$SchemaFile = Join-Path $RepoRoot "setup\create_schema_postgres.sql"

Write-Host "`n=== investment-forecaster setup ===" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Read Postgres credentials from secrets file
# ---------------------------------------------------------------------------
Write-Host "`n[1/6] Reading credentials from $SecretsFile..."

if (-not (Test-Path $SecretsFile)) {
    Write-Error "Secrets file not found: $SecretsFile"
    exit 1
}

$PgUser     = python -c "import sys; sys.path.insert(0, r'C:\Users\james\GitHub\Secrets'); from postgres import postgres_user; print(postgres_user)"
$PgPassword = python -c "import sys; sys.path.insert(0, r'C:\Users\james\GitHub\Secrets'); from postgres import postgres_password; print(postgres_password)"
$PgHost     = python -c "import sys; sys.path.insert(0, r'C:\Users\james\GitHub\Secrets'); from postgres import dsn; print(dsn)"

if (-not $PgUser -or -not $PgPassword -or -not $PgHost) {
    Write-Error "Failed to read credentials from $SecretsFile"
    exit 1
}

Write-Host "  user=$PgUser  host=$PgHost  OK"

# ---------------------------------------------------------------------------
# 2. Write .env
# ---------------------------------------------------------------------------
Write-Host "`n[2/6] Writing $EnvFile..."

$EnvContent = @"
# PostgreSQL connection
DB_HOST=$PgHost
DB_PORT=5432
DB_NAME=investment_forecaster
DB_USER=$PgUser
DB_PASSWORD=$PgPassword

# Portfolio database (managed by investment-portfolio-manager)
PORTFOLIO_DB_NAME=investment_portfolio

# Anthropic API — fill in your key
ANTHROPIC_API_KEY=

# IBKR Client Portal Gateway
IBKR_GATEWAY_URL=https://localhost:5000
"@

Set-Content -Path $EnvFile -Value $EnvContent -Encoding UTF8
Write-Host "  Written to $EnvFile"

# ---------------------------------------------------------------------------
# 3. Create databases
# ---------------------------------------------------------------------------
Write-Host "`n[3/6] Creating databases (if they do not exist)..."

$Env:PGPASSWORD = $PgPassword

foreach ($DbName in @("investment_forecaster", "investment_portfolio")) {
    $Exists = psql -U $PgUser -h $PgHost -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'" postgres 2>$null
    if ($Exists -eq "1") {
        Write-Host "  $DbName already exists — skip"
    } else {
        psql -U $PgUser -h $PgHost -c "CREATE DATABASE $DbName;" postgres
        Write-Host "  Created $DbName"
    }
}

# ---------------------------------------------------------------------------
# 4. Apply schema to investment_forecaster
# ---------------------------------------------------------------------------
Write-Host "`n[4/6] Applying schema to investment_forecaster..."

psql -U $PgUser -h $PgHost -d investment_forecaster -f $SchemaFile
Write-Host "  Schema applied"

# ---------------------------------------------------------------------------
# 5. Install Python dependencies
# ---------------------------------------------------------------------------
Write-Host "`n[5/6] Installing Python dependencies..."

Set-Location $RepoRoot
pip install -r requirements.txt

# ---------------------------------------------------------------------------
# 6. Seed prompt registry
# ---------------------------------------------------------------------------
Write-Host "`n[6/6] Seeding prompt registry..."

python scripts/seed_prompt_registry.py

Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "Fill in ANTHROPIC_API_KEY in $EnvFile, then run:"
Write-Host "  python scripts/run_forecasts.py --symbol AAPL" -ForegroundColor Yellow
