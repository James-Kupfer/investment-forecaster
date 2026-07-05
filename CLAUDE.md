# investment-forecaster

LLM Superforecaster — applies Tetlock superforecaster discipline to investment positions.

> For full schema, module/function reference, and agent catalogue see `architecture.md`.

## Database
- SQL Server Express: `James-desktop\sqlexpress`
- **`InvestmentForecaster`** — this app's database (`db_cursor()` / `get_connection()`)
- **`InvestmentPortfolio`** — owned by `investment-portfolio-manager`; read via `portfolio_db_cursor()` / `get_portfolio_connection()` in `forecaster/db.py`
- Windows Authentication (`Trusted_Connection=yes`) — no credentials stored anywhere
- **Never store DB credentials in code or config files**

## Agent Conventions
- All LLM-calling agents subclass `BaseAgent` (`forecaster/agents/base.py`); set `agent_id` and `model` as class attributes; implement `_parse_response()`
- `log_call()` must be called immediately after every API call — never batched; call failures must still be logged
- One active prompt per agent (`is_active=1` in `prompt_registry`); never edit a prompt row in-place — deactivate old, insert new versioned row

## Prompt Registry
- Prompts live in the DB, not in code. Source of truth for seeding: `forecaster/agents/<agent>.md` files
- Update via `python scripts/update_prompt.py --agent <agent_id> --version <vX.Y>`
- Version format: `v1.0`, `v1.1`, etc.; `authored_by_model` records which model wrote it

## Migrations
- Files: `migrations/NNN_description.sql` (zero-padded three-digit prefix)
- Always use `IF NOT EXISTS` / `IF OBJECT_ID IS NULL` patterns — runner is idempotent
- Runner: `python scripts/run_migrations.py`

## Development Workflow
- Branch: `develop` for integration, `feature/` or `claude/` for development
- CI: GitHub Actions self-hosted runner on `JAMES-DESKTOP` (runner: `desktop-forecaster`), shell: `cmd` — runs unit tests only (`--ignore=tests/test_db.py`)
- Mock Anthropic API in unit tests (`unittest.mock.patch`) — `test_db.py` runs against live SQL Server, run manually or via scheduled workflow

## Environment
Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`. DB connection uses Windows Auth — no password needed.
