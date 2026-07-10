# investment-forecaster setup script
# Reads credentials from C:\Users\james\GitHub\Secrets\
# Run from the repo root:  .\setup\setup.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot      = Split-Path $PSScriptRoot -Parent
$SecretsDir    = "C:\Users\james\GitHub\Secrets"
$PgSecretsFile = Join-Path $SecretsDir "postgres.py"
$AnthropicFile = Join-Path $SecretsDir "anthropic.py"
$EnvFile       = Join-Path $RepoRoot ".env"
$SchemaFile    = Join-Path $RepoRoot "setup\create_schema_postgres.sql"

Write-Host ""
Write-Host "=== investment-forecaster setup ===" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Read credentials from secrets files
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[1/6] Reading credentials from $SecretsDir..."

foreach ($f in @($PgSecretsFile, $AnthropicFile)) {
    if (-not (Test-Path $f)) {
        Write-Error "Secrets file not found: $f"
        exit 1
    }
}

$PgUser     = python -c "import sys; sys.path.insert(0, r'$SecretsDir'); from postgres import postgres_user; print(postgres_user)"
$PgPassword = python -c "import sys; sys.path.insert(0, r'$SecretsDir'); from postgres import postgres_password; print(postgres_password)"
$PgHost     = python -c "import sys; sys.path.insert(0, r'$SecretsDir'); from postgres import dsn; print(dsn)"

$AnthropicKey = python -c "import sys; sys.path.insert(0, r'$SecretsDir'); from anthropic import ANTHROPIC_API_KEY; print(ANTHROPIC_API_KEY)"

if (-not $PgUser -or -not $PgPassword -or -not $PgHost) {
    Write-Error "Failed to read Postgres credentials from $PgSecretsFile"
    exit 1
}
if (-not $AnthropicKey) {
    Write-Error "Failed to read ANTHROPIC_API_KEY from $AnthropicFile"
    exit 1
}

Write-Host "  user=$PgUser  host=$PgHost  anthropic key OK"

# ---------------------------------------------------------------------------
# 2. Write .env
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/6] Writing $EnvFile..."

$EnvLines = @(
    "# PostgreSQL connection",
    "DB_HOST=$PgHost",
    "DB_PORT=5432",
    "DB_NAME=investment_forecaster",
    "DB_USER=$PgUser",
    "DB_PASSWORD=$PgPassword",
    "",
    "# Portfolio database (managed by investment-portfolio-manager)",
    "PORTFOLIO_DB_NAME=investment_portfolio",
    "",
    "# Anthropic API",
    "ANTHROPIC_API_KEY=$AnthropicKey",
    "",
    "# IBKR Client Portal Gateway",
    "IBKR_GATEWAY_URL=https://localhost:5000"
)
$EnvLines | Set-Content -Path $EnvFile -Encoding UTF8

Write-Host "  Written to $EnvFile"

# ---------------------------------------------------------------------------
# 3. Create databases
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] Creating databases (if they do not exist)..."

$Env:PGPASSWORD = $PgPassword

foreach ($DbName in @("investment_forecaster", "investment_portfolio")) {
    $Exists = psql -U $PgUser -h $PgHost -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'" postgres 2>$null
    if ($Exists -eq "1") {
        Write-Host "  $DbName already exists, skipping"
    } else {
        psql -U $PgUser -h $PgHost -c "CREATE DATABASE $DbName;" postgres
        Write-Host "  Created $DbName"
    }
}

# ---------------------------------------------------------------------------
# 4. Apply schema to investment_forecaster
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/6] Applying schema to investment_forecaster..."

psql -U $PgUser -h $PgHost -d investment_forecaster -f $SchemaFile
Write-Host "  Schema applied"

# ---------------------------------------------------------------------------
# 5. Install Python dependencies
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/6] Installing Python dependencies..."

Set-Location $RepoRoot
pip install -r requirements.txt

# ---------------------------------------------------------------------------
# 6. Seed prompt registry
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[6/6] Seeding prompt registry..."

python scripts/seed_prompt_registry.py

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Run a forecast with:"
Write-Host "  python scripts/run_forecasts.py --symbol AAPL" -ForegroundColor Yellow
