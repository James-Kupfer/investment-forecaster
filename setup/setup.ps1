# investment-forecaster setup script
# Reads the Secrets folder location from config.toml (or FORECASTER_SECRETS_DIR)
# -- see config.example.toml. Run from the repo root:  .\setup\setup.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path $PSScriptRoot -Parent
$ConfigFile = Join-Path $RepoRoot "config.toml"
$SchemaFile = Join-Path $RepoRoot "setup\create_schema_postgres.sql"

Write-Host ""
Write-Host "=== investment-forecaster setup ===" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Resolve the Secrets folder and verify credentials are available there
#    (forecaster/credentials.py reads these directly at runtime — no .env)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[1/5] Resolving Secrets folder..."

if ($env:FORECASTER_SECRETS_DIR) {
    $SecretsDir = ($env:FORECASTER_SECRETS_DIR -split [System.IO.Path]::PathSeparator)[0]
} elseif (Test-Path $ConfigFile) {
    $SecretsDir = python -c "
import sys
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
with open(r'$ConfigFile', 'rb') as f:
    cfg = tomllib.load(f)
override = cfg.get('secrets', {}).get('override', [])
override = [override] if isinstance(override, str) else list(override)
print(override[0] if override else '')
"
} else {
    Write-Error "Neither FORECASTER_SECRETS_DIR nor $ConfigFile is set. Copy config.example.toml to config.toml and set [secrets] override to your Secrets folder first."
    exit 1
}

if (-not $SecretsDir) {
    Write-Error "Could not resolve a Secrets folder from config.toml or FORECASTER_SECRETS_DIR."
    exit 1
}

$PgSecretsFile = Join-Path $SecretsDir "postgres.py"
$AnthropicFile = Join-Path $SecretsDir "Anthropic.py"

Write-Host "  Using Secrets folder: $SecretsDir"
Write-Host ""
Write-Host "[1/5] Verifying credentials in $SecretsDir..."

foreach ($f in @($PgSecretsFile, $AnthropicFile)) {
    if (-not (Test-Path $f)) {
        Write-Error "Secrets file not found: $f"
        exit 1
    }
}

$PgUser     = python -c "import sys; sys.path.insert(0, r'$SecretsDir'); from postgres import postgres_user; print(postgres_user)"
$PgPassword = python -c "import sys; sys.path.insert(0, r'$SecretsDir'); from postgres import postgres_password; print(postgres_password)"
$PgHost     = python -c "import sys; sys.path.insert(0, r'$SecretsDir'); from postgres import dsn; print(dsn)"

$AnthropicContent = Get-Content $AnthropicFile -Raw
if ($AnthropicContent -match "ANTHROPIC_API_KEY\s*=\s*'([^']+)'") {
    $AnthropicKey = $Matches[1]
} elseif ($AnthropicContent -match 'ANTHROPIC_API_KEY\s*=\s*"([^"]+)"') {
    $AnthropicKey = $Matches[1]
} else {
    $AnthropicKey = ""
}

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
# 2. Create databases
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/5] Creating databases (if they do not exist)..."

# Locate psql if it is not already on PATH
$psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
$psql = if ($psqlCmd) { $psqlCmd.Source } else { $null }
if (-not $psql) {
    $candidates = Get-ChildItem "C:\Program Files\PostgreSQL" -Filter psql.exe -Recurse -ErrorAction SilentlyContinue |
                  Sort-Object FullName -Descending |
                  Select-Object -First 1
    if ($candidates) {
        $psql = $candidates.FullName
        Write-Host "  Found psql at $psql"
    } else {
        Write-Error "psql not found. Add PostgreSQL\bin to PATH or install PostgreSQL."
        exit 1
    }
}

$Env:PGPASSWORD = $PgPassword

foreach ($DbName in @("investment_forecaster", "investment_portfolio")) {
    $CheckSql = "SELECT 1 FROM pg_database WHERE datname='" + $DbName + "'"
    $Exists = & $psql -U $PgUser -h $PgHost -tAc $CheckSql postgres 2>$null
    if ($Exists -eq "1") {
        Write-Host "  $DbName already exists, skipping"
    } else {
        $CreateSql = "CREATE DATABASE " + $DbName + ";"
        & $psql -U $PgUser -h $PgHost -c $CreateSql postgres
        Write-Host "  Created $DbName"
    }
}

# ---------------------------------------------------------------------------
# 3. Apply schema to investment_forecaster
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/5] Applying schema to investment_forecaster..."

& $psql -U $PgUser -h $PgHost -d investment_forecaster -f $SchemaFile
Write-Host "  Schema applied"

# ---------------------------------------------------------------------------
# 4. Install Python dependencies
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/5] Installing Python dependencies..."

Set-Location $RepoRoot
pip install -r requirements.txt

# ---------------------------------------------------------------------------
# 5. Seed prompt registry
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/5] Seeding prompt registry..."

python scripts/seed_prompt_registry.py

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Run a forecast with:"
Write-Host "  python scripts/run_forecasts.py --symbol AAPL" -ForegroundColor Yellow
