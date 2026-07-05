# investment-forecaster

LLM Superforecaster — applies Tetlock superforecaster discipline to investment positions.

## Architecture

### Database
- SQL Server Express: `James-desktop\sqlexpress`, database `InvestmentForecaster`
- Windows Authentication (Trusted_Connection=yes) — no credentials stored
- Connection via `forecaster/db.py`: `get_connection()` and `db_cursor()` context manager
- Never store DB credentials in code or config files

### Agent Pattern
All agents inherit from `BaseAgent` (`forecaster/agents/base.py`):
- Class attributes: `agent_id` (matches `prompt_registry.agent_id`), `model`
- `get_active_prompt()` → queries `prompt_registry` WHERE `is_active=1`
- `call(messages, system, max_tokens)` → Anthropic API, returns `AgentResult`
- `log_call(result, forecast_id, macro_state_id)` → writes `llm_call_log` immediately (never batched)
- `_parse_response(response)` → abstract, implement per agent

### Prompt Registry
Prompts live in the `prompt_registry` table, not in code. Seeded by `scripts/seed_prompt_registry.py`.
- Each agent has one active prompt (`is_active=1`) at a time
- Version format: `v1.0`, `v1.1`, etc.
- `authored_by_model` records which model wrote the prompt
- Update prompts via SQL UPDATE + new INSERT, never edit in place

### Pipeline Orchestration
`forecaster/pipeline.py` — `ForecastPipeline.run(symbol)`:
1. Triage gate (TriageAgent)
2. Question Definition
3. MacroQ (daily job, cached in `macro_state`)
4. Risk Judge
5. Earnings + Primary Source (parallel, ThreadPoolExecutor)
6. Momentum + Trend + Volume + Pattern (parallel), then Technical Judge
7. Elicitation
8. Review
9. Confidence Judge
10. Aggregation

**forecast_id ordering**: A partial `forecasts` row (symbol + forecast_date) is inserted at
pipeline start to get an ID. All `llm_call_log` entries use this ID. Columns are updated
incrementally as agents complete.

**Parallelism**: `concurrent.futures.ThreadPoolExecutor(max_workers=4)` for layers 5 and 6.

### Market Data
`yfinance` is the data source:
- MacroQ: VIX (`^VIX`), DXY (`DX-Y.NYB`), rates (`^TNX`, `^IRX`), sector ETFs
- TA preprocessing: OHLCV history per symbol via `forecaster/talib_preprocess.py`
- Resolution scoring: closing price on `resolution_date`

### Migrations
- Files: `migrations/NNN_description.sql` (zero-padded three-digit prefix)
- Runner: `python scripts/run_migrations.py` — idempotent, splits on `GO`, commits per file
- Always use `IF NOT EXISTS` / `IF OBJECT_ID IS NULL` patterns for idempotency
- Naming convention: `001_initial_schema.sql`, `002_add_column.sql`, etc.

### Brier Scoring
`scripts/run_resolution.py` resolves positions at `resolution_date`:
- Fetches closing price via yfinance
- Calculates Brier score per agent per forecast
- Updates `agent_weights` table for model substitution calibration

## Development Workflow
- Branch: `develop` for integration, `feature/` or `claude/` for development
- CI: GitHub Actions self-hosted runner on desktop — runs migrations + pytest on every push
- Tests in `tests/` — mock Anthropic API calls in unit tests (`unittest.mock.patch`)
- DB tests (`test_db.py`) run against live SQL Server via self-hosted runner

## Environment
Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`. DB connection uses Windows Auth — no password needed.
