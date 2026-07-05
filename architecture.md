# investment-forecaster — Architecture

Multi-agent LLM pipeline that applies Tetlock superforecaster discipline to investment positions. For each position it runs 13 agents in a defined sequence, producing calibrated probability estimates for upside and downside outcomes. Results are stored in SQL Server and scored via Brier scoring after resolution.

---

## Repository Layout

```
investment-forecaster/
├── migrations/
│   └── 001_initial_schema.sql      # Creates InvestmentForecaster DB + all tables
├── forecaster/
│   ├── db.py                       # DB connection, db_cursor(), update_forecast_columns()
│   ├── pipeline.py                 # ForecastPipeline — orchestrates all 13 agents
│   ├── talib_preprocess.py         # yfinance + TA-Lib → plain-English indicator descriptions
│   ├── utils.py                    # extract_json() helper
│   └── agents/
│       ├── base.py                 # BaseAgent ABC + AgentResult dataclass
│       ├── triage.py               # TriageAgent (no LLM — threshold gate)
│       ├── question_definition.py  # QuestionDefinitionAgent
│       ├── macroq.py               # MacroQAgent + macro data fetch
│       ├── risk_judge.py           # RiskJudgeAgent
│       ├── elicitation.py          # ElicitationAgent
│       ├── review.py               # ReviewAgent
│       ├── confidence_judge.py     # ConfidenceJudgeAgent
│       ├── aggregation.py          # AggregationAgent (final output)
│       ├── research/
│       │   ├── earnings.py         # EarningsAgent
│       │   └── primary_source.py   # PrimarySourceAgent
│       └── technical/
│           ├── momentum.py         # MomentumAgent
│           ├── trend.py            # TrendAgent
│           ├── volume.py           # VolumeAgent
│           ├── pattern.py          # PatternAgent
│           └── judge.py            # TechnicalJudgeAgent
├── scripts/
│   ├── run_migrations.py           # Idempotent migration runner
│   ├── seed_prompt_registry.py     # Seeds DB with prompts from agent .md files
│   ├── update_prompt.py            # CLI to update a single agent's prompt
│   ├── run_macroq.py               # Daily MacroQ job
│   ├── run_forecasts.py            # Per-position forecast job
│   └── run_resolution.py           # Brier scoring + agent_weights update
├── tests/
│   ├── test_db.py                  # Live DB tests (self-hosted runner)
│   └── test_agents.py              # Agent unit tests (mocked Anthropic API)
├── .github/workflows/ci.yml        # Self-hosted runner CI
├── CLAUDE.md                       # Dev conventions
└── architecture.md                 # This file
```

Each agent also has a companion `.md` file in `forecaster/agents/` containing its prompt text. These are read by `seed_prompt_registry.py` to populate the `prompt_registry` table.

---

## Database

**Instance:** `James-desktop\sqlexpress`  
**Database:** `InvestmentForecaster`  
**Auth:** Windows Authentication (`Trusted_Connection=yes`) — no credentials stored.

### Tables

#### `prompt_registry`
One row per prompt version per agent. Only one row per `agent_id` has `is_active = 1`.

| Column | Type | Notes |
|---|---|---|
| `id` | INT IDENTITY | PK; referenced by `llm_call_log.prompt_version_id` |
| `agent_id` | NVARCHAR(100) | Matches `BaseAgent.agent_id`, e.g. `"elicitation"` |
| `version` | NVARCHAR(20) | e.g. `"v1.1"` |
| `prompt_text` | NVARCHAR(MAX) | Full system prompt |
| `is_active` | BIT | Exactly one active per `agent_id` at a time |
| `authored_by_model` | NVARCHAR(100) | Model that wrote the prompt |
| `created_at` | DATETIME2 | |

#### `macro_state`
One row per node per MacroQ run. Forms a tree: root node has `parent_node_id = NULL`.

| Column | Type | Notes |
|---|---|---|
| `id` | INT IDENTITY | PK |
| `node_id` | NVARCHAR(100) UNIQUE | Stable run-scoped ID (appended with 6-char UUID suffix) |
| `parent_node_id` | NVARCHAR(100) | References `node_id` of parent (logical, not FK) |
| `macro_date` | DATE | |
| `composite_score` | FLOAT | 0–1 regime score |
| `composite_confidence` | NVARCHAR(20) | high / medium / low |
| `composite_rationale` | NVARCHAR(1000) | |
| `rates_signal` | NVARCHAR(50) | |
| `rates_confidence` | NVARCHAR(20) | |
| `dxy_signal` | NVARCHAR(50) | |
| `dxy_confidence` | NVARCHAR(20) | |
| `vix_signal` | NVARCHAR(50) | |
| `vix_confidence` | NVARCHAR(20) | |
| `sector_signal` | NVARCHAR(50) | |
| `sector_confidence` | NVARCHAR(20) | |
| `node_rationale` | NVARCHAR(1000) | |
| `executing_model` | NVARCHAR(100) | |
| `prompt_version_id` | INT | FK → `prompt_registry.id` |
| `created_at` | DATETIME2 | |

#### `forecasts`
One row per pipeline run per position. Inserted as a partial row at pipeline start (to establish `id` for `llm_call_log` FKs); columns filled incrementally as agents complete.

Key columns (abbreviated — see migration for full list):

| Column | Notes |
|---|---|
| `id` | PK |
| `symbol` | Position ticker |
| `forecast_date` | Date pipeline ran |
| `resolution_date` | `forecast_date + horizon_days` |
| `macroq_node_id`, `macroq_p`, `macroq_confidence`, `macroq_rationale` | MacroQ root node output |
| `invq1_p`, `invq1_confidence`, `invq1_rationale`, `invq1_model`, `invq1_prompt_version` | Upside probability (from Aggregation) |
| `invq2_p`, `invq2_confidence`, `invq2_rationale`, `invq2_model`, `invq2_prompt_version` | Downside probability (from Aggregation) |
| `compound_conviction` | Weighted conviction score |
| `asymmetry_ratio` | `invq1_p / invq2_p` |
| `resolved` | BIT — set by resolution job |
| `resolved_outcome` | Text summary of actual outcome |
| `brier_q1`, `brier_q2` | Brier scores: `(probability - outcome)²` |

#### `llm_call_log`
One row per Anthropic API call. Written immediately after each call — never batched.

| Column | Notes |
|---|---|
| `forecast_id` | FK → `forecasts.id` (nullable for MacroQ-only calls) |
| `macro_state_id` | FK → `macro_state.id` (nullable) |
| `agent_id` | Which agent made the call |
| `prompt_version_id` | FK → `prompt_registry.id` |
| `executing_model` | Model ID string |
| `tokens_in`, `tokens_out`, `tokens_cached` | Usage |
| `call_cost_usd` | Computed from pricing table in `base.py` |
| `duration_ms` | Wall-clock time |
| `error` | Non-null if the call failed |

#### `agent_weights`
Rolling accuracy per agent per question type per model. Updated by the resolution job.

PK: `(agent_id, question_type, model_id)`

| Column | Notes |
|---|---|
| `rolling_accuracy` | Running mean of `1 - brier_score` |
| `sample_size` | Number of resolved forecasts |
| `last_updated` | |

---

## Core Modules

### `forecaster/db.py`

DB connection layer. Reads `DB_SERVER`, `DB_NAME`, `DB_DRIVER` from environment / `.env`.

| Symbol | Description |
|---|---|
| `get_connection() → pyodbc.Connection` | Opens pyodbc connection with Windows Auth |
| `db_cursor()` | Context manager: yields cursor, commits on exit, rolls back on exception, always closes connection |
| `update_forecast_columns(forecast_id, **kwargs)` | Builds `UPDATE forecasts SET col=? ... WHERE id=?` dynamically from kwargs; no-op if kwargs empty |

---

### `forecaster/utils.py`

| Function | Description |
|---|---|
| `extract_json(text) → dict` | Extracts the first JSON object from LLM response text. Tries: direct parse → fenced ` ```json ``` ` block → bare `{...}` match. Returns `{}` on total failure. |

---

### `forecaster/talib_preprocess.py`

Converts raw price data into plain-English strings suitable for LLM context. Falls back to pandas calculations if TA-Lib is not installed.

| Function | Description |
|---|---|
| `fetch_ohlcv(symbol, period="6mo") → DataFrame` | Downloads OHLCV history via `yfinance`. Raises `ValueError` if empty. |
| `describe_rsi(df, period=14) → str` | RSI value + zone label (overbought ≥70, oversold ≤30, neutral) |
| `describe_macd(df) → str` | MACD direction (bullish/bearish) + crossover detection |
| `describe_ma_alignment(df) → str` | Price vs MA20/MA50/MA200 stack description (bullish stack, bearish stack, mixed) |
| `describe_adx(df, period=14) → str` | ADX trend-strength label (very strong ≥40, trending ≥25, weak) |
| `describe_volume(df, lookback=20) → str` | Current volume vs 20-day average ratio + label |
| `get_technical_context(symbol, period="6mo") → dict[str, str]` | Calls all five describers and returns `{rsi, macd, ma_alignment, adx, volume}` |

---

## Agent System

### `forecaster/agents/base.py`

All agents (except `TriageAgent`) inherit from `BaseAgent`.

#### `AgentResult` (dataclass)

Fields: `agent_id`, `model_id`, `prompt_version_id`, `tokens_in`, `tokens_out`, `tokens_cached`, `call_cost_usd`, `duration_ms`, `output: dict`, `error: Optional[str]`

#### `BaseAgent` (ABC)

Class attributes (defined on subclasses): `agent_id: str`, `model: str`

| Method | Description |
|---|---|
| `__init__()` | Creates `anthropic.Anthropic()` client |
| `get_active_prompt() → (int, str)` | Queries `prompt_registry` for `is_active=1` row matching `self.agent_id`. Returns `(id, prompt_text)`. |
| `call(messages, system=None, max_tokens=1024) → AgentResult` | Makes Anthropic API call; calls `_parse_response()`; computes cost and duration. On exception, captures error string and returns empty `output`. |
| `log_call(result, forecast_id=None, macro_state_id=None)` | Writes one row to `llm_call_log` immediately. Never batched. |
| `_parse_response(response) → dict` | **Abstract.** Each agent implements JSON extraction from the response. |
| `_compute_cost(tokens_in, tokens_out, tokens_cached) → float` | Looks up per-model pricing from `_PRICING` dict (Sonnet: $3/$15/$0.30 per MTok; Haiku: $1/$5/$0.10). |

**Pricing table** (`_PRICING`):
- `claude-sonnet-4-6`: $3.00 in / $15.00 out / $0.30 cached per MTok
- `claude-haiku-4-5-20251001`: $1.00 in / $5.00 out / $0.10 cached per MTok

---

### Agent Catalogue

Each agent's `run()` method calls `get_active_prompt()`, builds messages, calls `self.call()`, calls `self.log_call()`, writes columns to `forecasts` via `update_forecast_columns()`, and returns an `AgentResult`.

#### `TriageAgent` (no LLM)
- **Input:** `prior_compound_conviction: Optional[float]`
- **Logic:** Returns `True` (proceed) if `prior_conviction is None` (first run) or `≥ 0.30`. Otherwise rejects.
- **No DB writes, no API call.**

#### `QuestionDefinitionAgent`
- **agent_id:** `question_definition` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `thesis`, `horizon_days`, `forecast_id`
- **Output fields:** `question` (binary yes/no), `resolution_criteria`, `confidence`
- **DB writes:** `forecasts` — question-definition columns

#### `MacroQAgent`
- **agent_id:** `macroq` | **model:** `claude-sonnet-4-6`
- **Input:** `forecast_id` (optional), `macro_state_id` (optional)
- **Pre-LLM:** `_fetch_macro_snapshot()` pulls live data from yfinance for VIX, DXY, 10Y/2Y rates, and 6 sector ETFs (XLK, XLE, XME, XLF, XLV, XLI) — returns latest price + 1-month return for each.
- **Output:** JSON decision tree with nodes (`node_id`, `parent_node_id`, scores, signals per indicator)
- **DB writes:** Inserts all nodes into `macro_state` via `_persist_tree()` (UUID suffix prevents daily collisions); writes root node summary to `forecasts`
- **Can run standalone** (daily job) — `forecast_id` is optional.

#### `RiskJudgeAgent`
- **agent_id:** `risk_judge` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `thesis`, `macro_summary`, `forecast_id`, `macro_state_id`
- **Output fields:** enumerated risks (5 categories), `invq2_floor` (minimum downside probability), `confidence`, `rationale`
- **DB writes:** `forecasts` — risk judge columns

#### `EarningsAgent`
- **agent_id:** `earnings` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `thesis`, `forecast_id`, `macro_state_id`
- **Output fields:** `earnings_signal`, `earnings_trend`, `fcf_assessment`, `confidence`, `rationale`
- **DB writes:** `forecasts` — earnings columns
- **Runs parallel with** `PrimarySourceAgent`

#### `PrimarySourceAgent`
- **agent_id:** `primary_source` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `thesis`, `forecast_id`, `macro_state_id`
- **Output fields:** `primary_signal`, `evidence_weight`, `confidence`, `rationale`
- **DB writes:** `forecasts` — primary source columns
- **Runs parallel with** `EarningsAgent`

#### `MomentumAgent`
- **agent_id:** `momentum` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `tech_context: dict`, `forecast_id`, `macro_state_id`
- **Output fields:** `momentum_signal`, `rsi_value`, `macd_signal`, `roc`, `confidence`, `rationale`
- **DB writes:** `forecasts` — momentum columns
- **Runs parallel with** Trend, Volume, Pattern

#### `TrendAgent`
- **agent_id:** `trend` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `tech_context`, `forecast_id`, `macro_state_id`
- **Output fields:** `trend_signal`, `ma_alignment`, `confidence`, `rationale`
- **DB writes:** `forecasts` — trend columns

#### `VolumeAgent`
- **agent_id:** `volume` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `tech_context`, `forecast_id`, `macro_state_id`
- **Output fields:** `volume_signal`, `confidence`, `rationale`
- **DB writes:** `forecasts` — volume columns

#### `PatternAgent`
- **agent_id:** `pattern` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `tech_context`, `forecast_id`, `macro_state_id`
- **Output fields:** `pattern_signal`, `key_level`, `reliability`, `confidence`, `rationale`
- **DB writes:** `forecasts` — pattern columns

#### `TechnicalJudgeAgent`
- **agent_id:** `tech_judge` | **model:** `claude-sonnet-4-6`
- **Input:** `tech_results: list[AgentResult]` (momentum, trend, volume, pattern outputs), `forecast_id`, `macro_state_id`
- **Output fields:** `technical_signal`, `key_level`, `dissenting_signals`, `confidence`, `rationale`
- **DB writes:** `forecasts` — technical judge columns

#### `ElicitationAgent`
- **agent_id:** `elicitation` | **model:** `claude-sonnet-4-6`
- **Input:** `symbol`, `question`, `all_context: dict`, `forecast_id`, `macro_state_id`
- **Methodology:** Reference class → inside view → pre-mortem → synthesis. Outputs calibrated probability.
- **Output fields:** `invq3_p` (probability estimate), `reference_class`, `inside_view`, `premortem`, `confidence`, `rationale`
- **DB writes:** `forecasts` — elicitation (invq3) columns

#### `ReviewAgent`
- **agent_id:** `review` | **model:** `claude-sonnet-4-6`
- **Input:** `elicitation_output`, `all_context`, `forecast_id`, `macro_state_id`
- **Checks:** confirmation bias, overconfidence, anchoring, base rate neglect, narrative fallacy
- **Output fields:** `review_flag` (bool), `revised_probability` (if flag=True), `confidence`, `rationale`
- **DB writes:** `forecasts` — review columns

#### `ConfidenceJudgeAgent`
- **agent_id:** `confidence_judge` | **model:** `claude-sonnet-4-6`
- **Input:** `elicitation_output`, `review_output`, `forecast_id`, `macro_state_id`
- **Logic:** Uses `revised_probability` if `review_flag=True`; applies shrinkage toward outside view if inside/outside views diverge by >0.20; computes CI width and `sizing_haircut`.
- **Output fields:** `final_probability`, `ci_lower`, `ci_upper`, `sizing_haircut`, `confidence`, `rationale`
- **DB writes:** `forecasts` — confidence judge columns

#### `AggregationAgent`
- **agent_id:** `aggregation` | **model:** `claude-sonnet-4-6`
- **Input:** `all_outputs: dict` (all prior agent outputs), `forecast_id`, `macro_state_id`
- **Output fields:** `upside_probability` (invq1), `downside_probability` (invq2), `compound_conviction`, `asymmetry_ratio`, `thesis_crux`, `summary`, `confidence`
- **DB writes:** `forecasts` — invq1/invq2/conviction/asymmetry columns
- **Note:** `asymmetry_ratio` is recomputed locally if not returned by LLM.

---

## Pipeline Orchestrator

### `forecaster/pipeline.py` — `ForecastPipeline`

| Method | Description |
|---|---|
| `__init__(max_workers=4)` | Sets thread pool size for parallel layers |
| `run(symbol, question_horizon_days=90) → Optional[int]` | Full pipeline. Returns `forecast_id` or `None` if triage rejects. |
| `_get_prior_conviction(symbol) → Optional[float]` | Queries most recent `compound_conviction` from `forecasts` for this symbol |
| `_get_thesis(symbol) → str` | Reads `investment_thesis` from `positions` table (cross-DB: reads from `InvestmentPortfolio`) |
| `_insert_partial_forecast(symbol, forecast_date, resolution_date) → int` | Inserts skeleton `forecasts` row; returns new `id` via `OUTPUT INSERTED.id` |
| `_run_parallel(callables) → list` | Executes list of callables concurrently with `ThreadPoolExecutor`; returns results in submission order |

### Pipeline Execution Order

```
1.  TriageAgent          — reject if prior compound_conviction < 0.30
    ↓ (pass)
2.  [Insert partial forecasts row] — establishes forecast_id for all FK references
    ↓
3.  QuestionDefinitionAgent    — defines binary question + resolution criteria
    ↓
4.  MacroQAgent               — macro regime tree (live yfinance data)
    ↓
5.  RiskJudgeAgent             — risk enumeration + invq2_floor
    ↓
6a. EarningsAgent    ─┐
6b. PrimarySourceAgent─┘  (parallel, ThreadPoolExecutor)
    also: get_technical_context() runs concurrently
    ↓
7a. MomentumAgent ─┐
7b. TrendAgent    ─┤  (parallel)
7c. VolumeAgent   ─┤
7d. PatternAgent  ─┘
    ↓
8.  TechnicalJudgeAgent   — synthesises 4 technical signals
    ↓
9.  ElicitationAgent      — Tetlock 4-step probability estimate
    ↓
10. ReviewAgent            — bias check; may revise probability
    ↓
11. ConfidenceJudgeAgent   — calibrated final probability + CI + sizing haircut
    ↓
12. AggregationAgent       — final upside/downside probs + thesis crux + summary
```

---

## Scripts

### `scripts/run_migrations.py`
Idempotent migration runner. Reads all `migrations/NNN_*.sql` files in order, splits on `GO`, executes each batch with `autocommit=True`. Tracks applied migrations to avoid re-running.

### `scripts/seed_prompt_registry.py`
Reads each `forecaster/agents/<agent>.md` file and inserts a row into `prompt_registry` (`is_active=1`) for each agent that doesn't already have an active prompt. Idempotent — skips agents that already have an active entry.

### `scripts/update_prompt.py`
CLI for updating a single agent's prompt without re-seeding:
```
python scripts/update_prompt.py --agent elicitation --version v1.2
```
Sets old active prompt to `is_active=0`, inserts new row with incremented version.

### `scripts/run_macroq.py`
Runs `MacroQAgent().run()` once. Intended for Windows Task Scheduler (daily, pre-market). Exits with code 1 on error.

### `scripts/run_forecasts.py`
Runs `ForecastPipeline` for every `status='active'` position, or a single symbol via `--symbol TICKER`. Exits with code 1 if any symbol fails.

```
python scripts/run_forecasts.py
python scripts/run_forecasts.py --symbol AAPL
python scripts/run_forecasts.py --symbol AAPL --horizon 60
```

### `scripts/run_resolution.py`
Resolves past-due forecasts:
1. Queries `forecasts` where `resolved=0` and `resolution_date ≤ today`
2. For each: fetches closing price at `forecast_date` and `resolution_date` via yfinance
3. Computes `pct_change`; binary outcome: `invq1` hits if `pct_change ≥ upside_threshold`; `invq2` hits if `pct_change ≤ -drawdown_threshold`
4. Computes `brier_q1/brier_q2 = (probability - outcome)²`
5. Updates `forecasts.resolved=1` + `resolved_outcome` + Brier scores
6. Updates `agent_weights` rolling accuracy (running mean of `1 - brier_score`)

---

## Tests

### `tests/test_db.py`
Live DB tests — run on self-hosted runner against `InvestmentForecaster`. Verifies connection, table existence, and prompt_registry schema.

### `tests/test_agents.py`
Unit tests with mocked Anthropic API (`unittest.mock.patch`). Does not require API key or DB. Covers `BaseAgent.call()`, `log_call()`, cost computation, and `extract_json()` edge cases.

Run: `python -m pytest`

---

## CI

`.github/workflows/ci.yml` — self-hosted runner on `JAMES-DESKTOP` (runner name: `desktop-forecaster`), shell: `cmd`.

Steps:
1. Checkout
2. `pip install -r requirements.txt`
3. `python scripts/run_migrations.py` — applies any new migrations to `InvestmentForecaster`
4. `python scripts/seed_prompt_registry.py` — seeds prompts if not already present
5. `python -m pytest`

Environment: `DB_SERVER=James-desktop\sqlexpress`, `DB_NAME=InvestmentForecaster`, `ANTHROPIC_API_KEY` (from GitHub Actions secret).

---

## Cross-Repo Dependency

`ForecastPipeline._get_thesis()` reads `investment_thesis` from the `positions` table in `InvestmentPortfolio` (managed by `investment-portfolio-manager`). This is a **cross-database read** on the same SQL Server instance. The pipeline also reads `upside_threshold` and `drawdown_threshold` from `positions` during resolution scoring.

Run `investment-portfolio-manager` sync first to ensure positions are up to date before running forecasts.

---

## Prompt Management

Prompts are stored in the database, not in code. The `.md` files in `forecaster/agents/` are the **source of truth for seeding** — they are read once by `seed_prompt_registry.py` and inserted into `prompt_registry`. After that, changes go through `update_prompt.py` (which versions the change) or direct SQL.

**Never edit a prompt in-place in the DB** — always deactivate the old row and insert a new versioned row. The `update_prompt.py` script enforces this.

---

## Extension Points

- **Add a new agent:** Create `forecaster/agents/my_agent.py` (subclass `BaseAgent`, set `agent_id` and `model`, implement `_parse_response()`), create `forecaster/agents/my_agent.md` (prompt text), add to `seed_prompt_registry.py`'s agent list, wire into `pipeline.py`.
- **Add a new migration:** Create `migrations/NNN_description.sql` with the next sequential number. Always use `IF OBJECT_ID IS NULL` / `IF NOT EXISTS` guards. `run_migrations.py` will pick it up automatically.
- **Change a model:** Update `model` class attribute on the agent class and add pricing to `_PRICING` in `base.py` if it's a new model.
- **Update a prompt:** Run `python scripts/update_prompt.py --agent <agent_id> --version <vX.Y>` after editing the `.md` file.
