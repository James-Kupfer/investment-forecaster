# investment-forecaster — Architecture

Deep technical reference: full database schema, every agent's inputs/outputs, and a module-by-module function reference. For what the system does, how triage works, and how to run it, start with [`README.md`](README.md) — this file assumes you've read that first.

This is the **v2 (decomposition) pipeline**. An earlier v1 design forecast a single upside/downside pair per position (`invq1`/`invq2`/`invq3` columns); it was retired in favor of decomposing each thesis into several independently-scored sub-questions. The v1 columns and the `run_resolution.py` legacy pass that resolved them have been dropped entirely (migration 011) — there is no historical v1 data left in this database.

---

## Repository Layout

```
investment-forecaster/
├── migrations/
│   ├── 001_initial_schema.sql          # Base schema (Postgres)
│   ├── 002-007_*.sql                   # No-ops — merged into 001 during the SQL Server -> Postgres port
│   ├── 008_decomposition_pipeline.sql  # forecast_questions table + v2 forecasts columns
│   ├── 009_asymmetry_adjustment.sql    # asymmetry_adjustment / buy_threshold_used / sell_threshold_used
│   └── 010_low_n_adjustment.sql        # question_count / low_n_adjustment
├── setup/
│   ├── create_schema_postgres.sql      # Full current schema in one file (used by setup.ps1)
│   ├── setup.ps1                       # Creates DBs, applies schema, installs deps, seeds prompts
│   └── install-runner.ps1              # Installs the self-hosted GitHub Actions runner
├── forecaster/
│   ├── config.py                       # SECRETS_DIRS — candidate paths for the shared Secrets folder
│   ├── credentials.py                  # Loads ANTHROPIC_API_KEY / DB_* / SEC_EDGAR_USER_AGENT at import time
│   ├── db.py                           # Connections + dynamic column-update helpers
│   ├── pipeline.py                     # ForecastPipeline — orchestrates the 4-stage pipeline
│   ├── edgar_client.py                 # SEC EDGAR client (XBRL financials, filings, Form 4)
│   ├── market_data.py                  # OHLCV fetch: IBKR cache -> IBKR Gateway -> Yahoo fallback chain
│   ├── ibkr_mcp_cache.py               # Reads ibkr_price_cache.json (populated externally)
│   ├── talib_preprocess.py             # OHLCV -> plain-English technical indicator descriptions
│   ├── utils.py                        # extract_json() helper
│   └── agents/
│       ├── base.py                     # BaseAgent ABC + AgentResult dataclass
│       ├── triage.py                   # TriageAgent (no LLM — threshold gate)
│       ├── question_definition.py      # QuestionDefinitionAgent
│       ├── macroq.py                   # MacroQAgent + macro data fetch
│       ├── risk_judge.py               # RiskJudgeAgent
│       ├── elicitation.py              # ElicitationAgent
│       ├── review.py                   # ReviewAgent
│       ├── confidence_judge.py         # ConfidenceJudgeAgent
│       ├── aggregation.py              # AggregationAgent (final output)
│       ├── research/
│       │   ├── earnings.py             # EarningsAgent
│       │   └── primary_source.py       # PrimarySourceAgent
│       └── technical/
│           ├── momentum.py             # MomentumAgent
│           ├── trend.py                # TrendAgent
│           ├── volume.py               # VolumeAgent
│           └── judge.py                # TechnicalJudgeAgent
├── personas/
│   ├── model_config.py                 # AGENT_MODELS — sole owner of agent -> model assignment
│   └── <agent>.md                      # One prompt-text file per agent (source of truth for seeding)
├── scripts/
│   ├── run_migrations.py               # Idempotent migration runner
│   ├── seed_prompt_registry.py         # Seeds DB with prompts from agent .md files
│   ├── update_prompt.py                # CLI to version-update a single agent's prompt
│   ├── run_macroq.py                   # Standalone daily MacroQ job
│   ├── run_forecasts.py                # Per-position / full-portfolio forecast job
│   ├── run_resolution.py               # Brier scoring + agent_weights update
│   └── run_pipeline.ps1                # Interactive launcher (Excel sync, symbol, force, all in one prompt)
├── tests/
│   ├── test_agents.py                  # Mocked-API unit tests for every agent + aggregation formulas
│   ├── test_pipeline.py                # ForecastPipeline._is_equity_like unit tests
│   ├── test_edgar_client.py            # Mocked SEC EDGAR client unit tests
│   ├── test_image_extractor.py         # Tests Technical Analysis/image_extractor.py
│   └── test_db.py                      # Live-DB integration tests (excluded from CI)
├── Technical Analysis/
│   ├── image_extractor.py              # Standalone PDF->PNG extractor (PyMuPDF), unrelated to the pipeline
│   └── Bulkowski_Encyclopedia_of_Chart_Patterns.pdf
├── run_pipeline.bat                    # Double-click wrapper for scripts/run_pipeline.ps1
├── .github/workflows/ci.yml            # Self-hosted runner CI
├── README.md                            # Start here
├── CLAUDE.md                            # AI coding assistant operating instructions
└── architecture.md                      # This file
```

Each agent also has a companion `.md` file in `personas/` containing its prompt text. These are read by `seed_prompt_registry.py` to populate the `prompt_registry` table — prompts are database rows, not code (see [Prompt Management](#prompt-management)).

---

## Database

**Host:** `localhost:5432` (default) · **Database:** `investment_forecaster` · **Auth:** `DB_USER`/`DB_PASSWORD` loaded from the shared `Secrets` folder by `forecaster/credentials.py` (never `.env` — see [`CLAUDE.md`](CLAUDE.md)).

The schema below reflects the state after all of `migrations/001` through `010` are applied (`setup/create_schema_postgres.sql` is an equivalent flattened copy).

### `prompt_registry`
One row per prompt version per agent. Only one row per `agent_id` has `is_active = TRUE`.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | Referenced by `llm_call_log.prompt_version_id` |
| `agent_id` | VARCHAR(100) | Matches `BaseAgent.agent_id`, e.g. `"elicitation"` |
| `version` / `prompt_version` | VARCHAR(20) | e.g. `"v1.1"` (both columns exist; `prompt_version` is the current one, defaults `'v1.0'`) |
| `prompt_text` | TEXT | Full system prompt |
| `is_active` | BOOLEAN | Exactly one active per `agent_id` at a time |
| `authored_by_model` | VARCHAR(100) | Model that wrote the prompt |
| `created_at` | TIMESTAMP | |

### `macro_state`
One row per node per MacroQ run. Forms a tree: the root node has `parent_node_id = NULL`.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `node_id` | VARCHAR(100) UNIQUE | Stable run-scoped ID (6-char UUID suffix prevents daily collisions) |
| `parent_node_id` | VARCHAR(100) | References `node_id` of parent (logical, not FK) |
| `macro_date` | DATE | |
| `composite_score` | DOUBLE PRECISION | 0–1 regime score |
| `composite_confidence` | VARCHAR(20) | high / medium / low |
| `composite_rationale` | TEXT | |
| `rates_signal`, `dxy_signal`, `vix_signal`, `sector_signal` | VARCHAR(50) | Each paired with a `*_confidence` VARCHAR(20) column |
| `node_rationale` | TEXT | |
| `executing_model` | VARCHAR(100) | |
| `prompt_version_id` | INTEGER FK → `prompt_registry.id` | |
| `created_at` | TIMESTAMP | |

### `forecasts`
One row per pipeline run per position. Inserted as a partial row at pipeline start (to establish `id` for `llm_call_log`/`forecast_questions` FKs); columns filled incrementally as agents complete. `schema_version` (SMALLINT, default 1, set to 2 by `AggregationAgent`) disambiguates a row's era.

**Base + shared-evidence columns** (written by every run, v1 or v2):

| Column | Notes |
|---|---|
| `id` | PK |
| `symbol`, `forecast_date`, `resolution_date` | |
| `macroq_node_id`, `macroq_p`, `macroq_confidence`, `macroq_rationale`, `macroq_output` | MacroQ root node output |
| `risk_judge_output`, `invq2_floor`, `risk_judge_confidence/rationale/model/prompt_version`, `scale_adjusted_density_flag` | RiskJudge output |
| `earnings_*`, `primary_*`, `momentum_*`, `trend_*`, `volume_*`, `technical_*` (tech_judge) | Per-agent signal/confidence/rationale/model/prompt_version/output columns |
| `question_def_output` | Raw QuestionDefinition output (decomposed sub-questions live in `forecast_questions`, not here) |

**v2 decomposition-pipeline columns** (added 008/009/010; the only columns `AggregationAgent` writes for the final recommendation):

| Column | Type | Notes |
|---|---|---|
| `mechanical_score` | NUMERIC(8,4) | Deterministic EV score — see [Aggregation](#aggregation--from-score-to-recommendation) |
| `adjusted_score` | NUMERIC(8,4) | `mechanical_score` + clamped LLM delta, in `[-1, 1]` — **this is what `TriageAgent` gates on** |
| `score_adjustment_rationale`, `decision_rationale` | TEXT | LLM's stated justification for its adjustment / recommendation |
| `expected_upside_impact`, `expected_downside_impact`, `upside_downside_ratio` | NUMERIC(8,4) | |
| `monitor_list` | TEXT (JSON) | Sub-signal-worthy items excluded from scoring |
| `nearterm_critical_high_count` | INTEGER | From `QuestionDefinitionAgent` |
| `scale_adjusted_density_flag` | BOOLEAN | From `RiskJudgeAgent` |
| `asymmetry_adjustment` | NUMERIC(8,4) | Points shifted toward risk tolerance from `asymmetric_rating` |
| `low_n_adjustment` | NUMERIC(8,4) | Points shifted toward hold from a thin `scored_count` |
| `question_count` | INTEGER | = `scored_count` from `compute_mechanical_score` |
| `buy_threshold_used`, `sell_threshold_used` | NUMERIC(8,4) | The actual thresholds applied this run, after both adjustments |
| `recommendation` | VARCHAR(20) | `buy` / `sell` / `hold` / `pass` |
| `aggregation_output` | TEXT (JSON) | Full raw LLM output from the aggregation call |

### `forecast_questions`
One row per decomposed sub-question (up to 7 per `forecast_id`). The core v2 table — this is where per-question forecasting output lives, not on `forecasts`.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `forecast_id` | INTEGER FK → `forecasts.id` | |
| `question_type` | VARCHAR(20) | `"catalyst"` or `"risk"` |
| `question_text`, `resolution_criteria` | TEXT | |
| `resolution_date` | DATE | |
| `resolution_source` | VARCHAR(20) | `"price"` (auto-resolvable) or `"filing"`/other (manual — see [Resolution](README.md#resolution-what-gets-auto-checked-and-what-doesnt) in the README) |
| `evidence_source` | VARCHAR(20) | Which Stage-B specialist is primary evidence: `earnings` / `primary_source` / `technical` / `macro` / `risk` |
| `impact_direction` | VARCHAR(1) | `"+"` (catalyst) or `"-"` (risk) |
| `impact_magnitude` | VARCHAR(20) | `critical` / `high` / `medium` / `low` — only `critical`/`high` carry nonzero weight in scoring |
| `decomposition_rationale` | TEXT | Why `question_definition` chose this question |
| `elicitation_p` | NUMERIC(5,4) | Raw probability from `ElicitationAgent`, pre-review |
| `review_flag`, `review_rationale` | BOOLEAN, TEXT | From `ReviewAgent` |
| `final_probability` | NUMERIC(5,4) | From `ConfidenceJudgeAgent` — what `AggregationAgent` scores |
| `confidence`, `model_id`, `forecast_rationale` | VARCHAR(10), VARCHAR(100), TEXT | From `ConfidenceJudgeAgent` |
| `rationale_quality_score`, `rationale_quality_notes` | NUMERIC(5,4), TEXT | From `AggregationAgent`'s per-question grading |
| `question_output` | TEXT (JSON) | Raw output, updated at each stage |
| `resolved`, `resolved_outcome`, `brier` | BOOLEAN, TEXT, NUMERIC(8,6) | Set by `run_resolution.py`'s v2 pass — `price`-sourced questions only |
| `created_at` | TIMESTAMP | |

Indexes: `idx_forecast_questions_forecast_id` on `forecast_id`; `idx_forecast_questions_unresolved` on `resolution_date WHERE resolved = FALSE`.

### `llm_call_log`
One row per Anthropic API call. Written immediately after each call — never batched (see [`CLAUDE.md`](CLAUDE.md)).

| Column | Notes |
|---|---|
| `forecast_id` | FK → `forecasts.id` (nullable for MacroQ-only calls) |
| `macro_state_id` | FK → `macro_state.id` (nullable) |
| `agent_id` | Which agent made the call |
| `prompt_version_id` | FK → `prompt_registry.id` |
| `executing_model` | Model ID string |
| `tokens_in`, `tokens_out`, `tokens_cached` | Usage |
| `call_cost_usd` | Computed from `_PRICING` in `base.py` |
| `duration_ms` | Wall-clock time |
| `error` | Non-null if the call failed |
| `response_text` | Raw extracted text block (added migration 006) |

### `agent_weights`
Rolling accuracy per agent per question type per model, updated by `run_resolution.py`.

PK: `(agent_id, question_type, model_id)`

| Column | Notes |
|---|---|
| `question_type` | A sub-question's own `catalyst`/`risk` type, keyed under `agent_id="confidence_judge"` |
| `rolling_accuracy` | Running mean of `1 - brier_score` |
| `sample_size` | Number of resolved forecasts |
| `last_updated` | |

### Other tables
`position_catalysts`, `position_sources`, `sync_log` exist in `001_initial_schema.sql` and `setup/create_schema_postgres.sql`, but no code in `forecaster/` or `scripts/` currently reads or writes them — they're schema-only at present, likely intended for a future feature.

`positions` (theses, risk ratings, thresholds) is **not** in this database — it lives in the separate `investment_portfolio` database, owned by a sibling repo. See [Cross-Repo Dependency](#cross-repo-dependency).

---

## Core Modules

### `forecaster/config.py`
Loads `config.toml` from the repo root (git-ignored — see `config.example.toml` for the template) and exposes three values: `SECRETS_DIRS` (an ordered list of candidate paths for the shared `Secrets` folder, from `[secrets] override` only — never falls back to `config.example.toml`'s value, which is a placeholder, not a safe default), `DATABASE` (the `[database]` table — `port`/`name`/`portfolio_db_name`), and `MARKET_DATA` (the `[market_data]` table — `ibkr_gateway_url`). `DATABASE`/`MARKET_DATA` ARE merged from `config.example.toml` (base) then `config.toml` (override) — those values are genuine, universally-safe defaults (the standard Postgres port, this app's fixed DB names), so `db.py`/`market_data.py` read them directly (`DATABASE['port']`, etc.) with no second, hardcoded-literal fallback of their own. The `FORECASTER_SECRETS_DIR` environment variable overrides `SECRETS_DIRS` when set, ahead of `config.toml` — the escape hatch for environments where a checked-out file can't be relied on to persist (e.g. `actions/checkout`'s default clean step removes git-ignored files from a self-hosted runner's working directory between runs). Uses stdlib `tomllib` on Python 3.11+, the `tomli` backport below that. Consumed by `credentials.py` (`SECRETS_DIRS`), `db.py` (`DATABASE`), and `market_data.py` (`MARKET_DATA`).

### `forecaster/credentials.py`
Loads `ANTHROPIC_API_KEY`, `DB_HOST`/`DB_USER`/`DB_PASSWORD`, and `SEC_EDGAR_USER_AGENT` directly from Python files in the shared `Secrets` folder (`postgres.py`; `Anthropic.py`/`api_key.py`; `SEC.py`/`sec_id.py`) via `importlib` file-path loading — deliberately not a `sys.path` import, to avoid `Secrets\Anthropic.py` shadowing the real `anthropic` SDK package. Sets values into `os.environ` via `setdefault` at import time. No `.env` file is used for secrets.

### `forecaster/db.py`
Thin, generic DB layer — no business logic.

| Symbol | Description |
|---|---|
| `get_connection()` | Opens a psycopg2 connection to `investment_forecaster` |
| `get_portfolio_connection()` | Opens a psycopg2 connection to `investment_portfolio` |
| `db_cursor()` | Context manager: yields a cursor on `investment_forecaster`, commits on exit, rolls back on exception |
| `portfolio_db_cursor()` | Same, for `investment_portfolio` |
| `update_forecast_columns(forecast_id, **kwargs)` | Builds `UPDATE forecasts SET col=... WHERE id=...` dynamically from kwargs; no-op if empty |
| `insert_forecast_question(forecast_id, **kwargs) -> int` | Inserts a `forecast_questions` row; returns its new `id` |
| `update_forecast_question_columns(question_id, **kwargs)` | Same dynamic-update pattern, for `forecast_questions` |

### `forecaster/edgar_client.py`
SEC EDGAR client, rate-limited to stay under SEC's ~10 req/sec fair-access guidance, requires `SEC_EDGAR_USER_AGENT`.

| Function | Description |
|---|---|
| `get_cik(symbol)` | Resolves a ticker to a CIK number |
| `get_company_facts(cik)` | Fetches XBRL company-facts JSON |
| `get_quarterly_financials(symbol)` | Real reported quarterly EPS/net income/OCF/capex/revenue — **not** consensus estimates, guidance, transcripts, or short interest, none of which EDGAR provides |
| `get_recent_filings(symbol)` | Recent 10-K/10-Q/20-F/8-K/6-K filing metadata |
| `fetch_filing_excerpt(url)` | HTML-stripped excerpt of a filing |
| `get_insider_transactions(symbol)` / `_parse_form4(...)` | Form 4 open-market insider buy/sell transactions |

### `forecaster/market_data.py`
`MarketDataFetcher.fetch_ohlcv(symbol)` tries, in order: `ibkr_mcp_cache` (a Claude-populated JSON cache) → `IbkrClient` (IBKR Client Portal REST API: `resolve_contract`, `fetch_ohlcv`) → a direct Yahoo Finance v8 chart-API call (bypasses `yfinance`'s cookie handshake, which fails on this network). Raises `ValueError` if all three fail.

### `forecaster/ibkr_mcp_cache.py`
Read-only reader for `ibkr_price_cache.json`. `get_ohlcv(symbol)` returns a DataFrame if a cache entry exists and is younger than `MAX_AGE_HOURS = 25`, else `None`.

### `forecaster/utils.py`
| Function | Description |
|---|---|
| `extract_json(text) -> dict` | Robust JSON extraction from LLM output: prefers a fenced `json` code block, then brace-depth-scanned top-level objects, and takes the **last** successfully-parsed object (handles LLMs that draft an object, self-correct with narrative, then emit a final object). Returns `{}` if nothing parses. |

### `forecaster/talib_preprocess.py`
OHLCV → plain-English strings for LLM context. Uses TA-Lib if installed, else a pandas-based fallback (logs a warning if TA-Lib is missing).

| Function | Description |
|---|---|
| `fetch_ohlcv(symbol, period="6mo")` | Downloads OHLCV history via `MarketDataFetcher` |
| `describe_rsi`, `describe_macd`, `describe_ma_alignment`, `describe_adx`, `describe_volume`, `describe_roc` | Plain-English indicator descriptions |
| `get_technical_context(symbol, period="6mo") -> dict` | Runs all describers, returns the dict passed to Momentum/Trend/Volume |

---

## Agent System

### `forecaster/agents/base.py`

#### `AgentResult` (dataclass)
`agent_id`, `model_id`, `prompt_version_id`, `tokens_in`, `tokens_out`, `tokens_cached`, `call_cost_usd`, `duration_ms`, `output: dict`, `error: Optional[str]`, `response_text: Optional[str]`.

#### `BaseAgent` (ABC)
Every LLM-calling agent subclasses this (`TriageAgent` doesn't — it makes no API calls). `agent_id` is a required class attribute; `model` is **not** set on the subclass — `__init__` looks it up from `personas/model_config.py`'s `AGENT_MODELS` and raises if the `agent_id` isn't listed there.

| Method | Description |
|---|---|
| `get_active_prompt() -> (id, prompt_text)` | Queries `prompt_registry` for the `is_active=TRUE` row for `self.agent_id` |
| `call(messages, system=None, max_tokens=1024) -> AgentResult` | Makes the Anthropic call via the **streaming** API (`.messages.stream(...)`, not `.create()` — the SDK refuses non-streaming calls it estimates could exceed 10 minutes, which large `max_tokens` budgets can trigger), parses via `_parse_response()`, computes cost/duration. Exceptions are captured into `error` with empty `output`, never raised. |
| `log_call(result, forecast_id=None, macro_state_id=None)` | Writes one row to `llm_call_log` immediately — never batched |
| `extract_text_block(response)` (static) | Returns the first block with a `.text` attribute — **required** for every `_parse_response()`, since models with extended thinking return a `ThinkingBlock` first, which has no `.text` |
| `_parse_response(response) -> dict` | **Abstract.** Each agent extracts JSON from the response text |
| `_compute_cost(...)` | Looks up per-model rates from `_PRICING` |

**Pricing table** (`_PRICING`, `$ per MTok` as `(input, output, cached_input)`) — update this whenever a new model is added to `AGENT_MODELS`:
- `claude-sonnet-5`: 3.00 / 15.00 / 0.30
- `claude-haiku-4-5-20251001`: 1.00 / 5.00 / 0.10
- `claude-opus-4-8`: 15.00 / 75.00 / 1.50

The active model per agent is defined in `personas/model_config.py` — check that file for the current assignment; it's been observed running all-Haiku during test phases with the intended production model commented out alongside it, so don't assume the docstrings above are the live config.

---

### Agent Catalogue

Each agent's `run()` calls `get_active_prompt()`, builds messages, calls `self.call()`, calls `self.log_call()`, writes its output columns, and returns an `AgentResult` (except `ElicitationAgent`/`ReviewAgent`/`ConfidenceJudgeAgent`, which write to `forecast_questions` via `update_forecast_question_columns`, and `TriageAgent`, which is a plain Python function with no DB writes at all).

#### `TriageAgent` (no LLM, no DB writes)
`forecaster/agents/triage.py`. `THRESHOLD = 0.30` (hardcoded class constant). `run(prior_adjusted_score: Optional[float]) -> bool` — `True` (proceed) if `prior_adjusted_score is None` (first run) or `abs(prior_adjusted_score) >= THRESHOLD`; `False` otherwise. See the README's [Triage](README.md#triage-the-gate-before-spending-any-money) section for the full behavioral explanation, including how `--force` is used to trigger a deliberate, per-symbol "has the thesis changed?" refresh outside the normal triage-gated schedule.

#### `QuestionDefinitionAgent`
**agent_id:** `question_definition`. **Input:** `symbol`, `position: dict`, `forecast_id`, `macro_state_id=None`. Decomposes `position["thesis"]` + risk fields into up to 7 (`MAX_QUESTIONS`) Critical/High-impact catalyst/risk sub-questions, each resolvable within ~12 months. Does not classify long/short. **Output:** `{questions: [...], monitor_list: [...], nearterm_critical_high_count}`. **Writes:** `forecasts.question_def_output`, `nearterm_critical_high_count`; each question is inserted into `forecast_questions` by `pipeline.py` (not by this agent directly).

#### `MacroQAgent`
**agent_id:** `macroq`. **Input:** `forecast_id=None`, `macro_state_id=None` — can run standalone (daily job, no position needed). Fetches a live snapshot (VIX, DXY, 10Y/2Y rates, 6 sector ETFs) via `MarketDataFetcher`, builds a macro decision tree. **Output:** `{root_macro_state_id, nodes: [...]}`. **Writes:** every node into `macro_state` (UUID-suffixed `node_id`s); root node summary into `forecasts.macroq_*` when `forecast_id` is given.

#### `RiskJudgeAgent`
**agent_id:** `risk_judge`. **Input:** `symbol`, `thesis`, `macro_summary`, `forecast_id`, `drawdown_threshold=None`, `nearterm_critical_high_count=None`, `business=None`, `competitive_landscape=None`, `financials=None`, `macro_state_id=None`. Symbol-level downside-floor backstop plus a scale-aware judgment of whether the sub-question density from decomposition is unusual for a company this size. **Output:** enumerated risks, `invq2_floor`, `scale_adjusted_density_flag`, `confidence`, `rationale`. **Writes:** `forecasts.risk_judge_*`.

#### `EarningsAgent`
`forecaster/agents/research/earnings.py`. **agent_id:** `earnings`. **Input:** `symbol`, `thesis`, `forecast_id`, `financials=None`, `instrument_type=None`, `macro_state_id=None`. Pulls quarterly XBRL via `edgar_client.get_quarterly_financials`; falls back to the position's free-text `financials` field or training knowledge if no EDGAR CIK match, labeling the fallback via `data_source` so rationale stays honest about provenance. **Output:** `earnings_signal`, `earnings_trend`, `fcf_assessment`, `confidence`, `rationale`. **Writes:** `forecasts.earnings_*`. Runs parallel with `PrimarySourceAgent`. Skipped for non-equity-like positions (see `ForecastPipeline._is_equity_like`).

#### `PrimarySourceAgent`
`forecaster/agents/research/primary_source.py`. **agent_id:** `primary_source`. Same input/fallback shape as `EarningsAgent`. Pulls filing excerpts and Form 4 insider transactions via `edgar_client`. **Output:** `primary_signal`, `evidence_weight`, `confidence`, `rationale`. **Writes:** `forecasts.primary_*`. Runs parallel with `EarningsAgent`.

#### `MomentumAgent` / `TrendAgent` / `VolumeAgent`
`forecaster/agents/technical/{momentum,trend,volume}.py`. **agent_id:** `momentum`/`trend`/`volume`. **Input:** `symbol`, `tech_context: dict` (from `get_technical_context`), `forecast_id`, `macro_state_id=None`. Each assesses one slice — RSI/MACD/ROC regime, MA-alignment/ADX trend regime, volume-confirms-trend — independently and in parallel. **Writes:** `forecasts.{momentum,trend,volume}_*`.

#### `TechnicalJudgeAgent`
`forecaster/agents/technical/judge.py`. **agent_id:** `tech_judge`. **Input:** `tech_results: list[AgentResult]` (Momentum/Trend/Volume outputs), `forecast_id`, `macro_state_id=None`. Synthesizes the three technical signals into one verdict, noting dissent. **Output:** `technical_signal`, `key_level`, `dissenting_signals`, `confidence`, `rationale`. **Writes:** `forecasts.technical_*`. The whole technical block (Momentum/Trend/Volume/TechnicalJudge) is skipped entirely if no price data source succeeds for the symbol (non-fatal to the rest of the pipeline).

#### `ElicitationAgent`
**agent_id:** `elicitation`. **Input:** `symbol`, `question: dict` (one sub-question), `symbol_context: dict` (all Stage-B output), `question_id`, `forecast_id`, `position=None`, `macro_state_id=None`. Forecasts **one** sub-question via reference class → inside view → pre-mortem → synthesis. **Output:** `elicitation_p`, `reference_class`, `inside_view`, `premortem`, `confidence`, `rationale`. **Writes:** `forecast_questions.elicitation_p`, `question_output`. Runs once per surviving sub-question, fanned out in parallel across all of them.

#### `ReviewAgent`
**agent_id:** `review`. **Input:** `question`, `elicitation_output`, `symbol_context`, `question_id`, `forecast_id`, `macro_state_id=None`. Devil's-advocate bias critique (confirmation bias, overconfidence, anchoring, base-rate neglect, narrative fallacy) scoped to that one sub-question only, never the whole thesis. **Output:** `review_flag`, `revised_probability` (if flagged), `confidence`, `rationale`. **Writes:** `forecast_questions.review_flag`, `review_rationale`, `question_output`.

#### `ConfidenceJudgeAgent`
**agent_id:** `confidence_judge`. **Input:** `elicitation_output`, `review_output`, `question_id`, `forecast_id`, `macro_state_id=None`. Uses the reviewed probability if `review_flag=True`; applies shrinkage toward the outside view when inside/outside estimates diverge by more than 0.20; computes a confidence interval. **Output:** `final_probability`, `ci_lower`, `ci_upper`, `confidence`, `rationale`. **Writes:** `forecast_questions.final_probability`, `confidence`, `model_id`, `forecast_rationale`, `question_output`. This is the probability `AggregationAgent` actually scores.

#### `AggregationAgent`
**agent_id:** `aggregation`. **Input:** `questions: list`, `monitor_list: list`, `risk_floor_output: dict`, `forecast_id`, `asymmetric_rating: Optional[str] = None`, `macro_state_id=None`. The final decision agent — see the dedicated section below. **Writes:** `forecasts.mechanical_score`, `adjusted_score`, `score_adjustment_rationale`, `decision_rationale`, `expected_upside_impact`, `expected_downside_impact`, `upside_downside_ratio`, `asymmetry_adjustment`, `low_n_adjustment`, `question_count`, `buy_threshold_used`, `sell_threshold_used`, `monitor_list`, `recommendation`, `aggregation_output`, `schema_version=2`; also `forecast_questions.rationale_quality_score`/`rationale_quality_notes` per question via its per-question grading.

`max_tokens=32000` for this call specifically — an 8096 budget was observed truncating mid-`decision_rationale` on a live 7-question run (thorough per-question grading notes × up to 7 questions adds up fast), and the underlying model has been observed drafting a full JSON object, writing a self-correcting narrative aside, then emitting a second complete object — `extract_json`'s "prefer the last complete object" behavior exists specifically to handle that, but the token budget still has to cover both attempts.

---

## Aggregation — from score to recommendation

`forecaster/agents/aggregation.py`. This is the one place a mechanical, auditable number turns into a buy/sell/hold/pass call, so it's worth reading exactly, not just in summary — the code below is the literal logic, not a paraphrase.

### `compute_mechanical_score(questions) -> (mechanical_score, upside_impact, downside_impact, upside_downside_ratio, scored_count)`

```python
_SEVERITY_WEIGHT = {"critical": 4, "high": 3}   # medium/low -> weight 0, excluded

for q in questions:
    p = q["final_probability"]
    weight = _SEVERITY_WEIGHT.get(q["impact_magnitude"], 0)
    if p is None or not weight:
        continue                       # not scored
    scored_count += 1
    contribution = p * weight
    if q["impact_direction"] == "+":
        upside_impact += contribution
    else:
        downside_impact += contribution

total = upside_impact + downside_impact
mechanical_score = (upside_impact - downside_impact) / total if total > 0 else 0.0
upside_downside_ratio = upside_impact / downside_impact if downside_impact > 0 else None
```

`mechanical_score` is normalized to `[-1, +1]` so positions are comparable regardless of how many sub-questions they have — but that same normalization is exactly what pins the score to `±1` whenever every scored question lands on the same side of the ledger (guaranteed at `scored_count=1`, likely at 2–3), since a lone question's probability affects only which side it's on, not the magnitude. `compute_low_n_adjustment` exists specifically to compensate for this.

### `compute_asymmetry_adjustment(asymmetric_rating) -> float`

```python
_ASYMMETRY_RATING_MULTIPLES = {"high": 10.0, "medium": 5.0, "low": 1.0, "no": 0.0}
_ASYMMETRY_REFERENCE_MULTIPLE = 10.0
_MAX_ASYMMETRY_ADJUSTMENT = 0.20

multiple = _ASYMMETRY_RATING_MULTIPLES.get(str(asymmetric_rating).strip().lower())
if not multiple:            # missing, "no", or unrecognized -> no shift
    return 0.0
scale = min(multiple / _ASYMMETRY_REFERENCE_MULTIPLE, 1.0)
return round(scale * _MAX_ASYMMETRY_ADJUSTMENT, 4)
```

`asymmetric_rating` comes from `positions.asymmetric_rating` (set by the sibling `investment-profile` skill): High/Medium/Low/No, rating the plausible ~1-year return path as High=10x, Medium≥5x, Low≥1x, else No. Result: **High → +0.20, Medium → +0.10, Low → +0.02, No/unrecognized → 0.0.**

### `compute_low_n_adjustment(scored_count) -> float`

```python
_FULL_QUESTION_COUNT = 4
_MAX_LOW_N_ADJUSTMENT = 0.20

if scored_count <= 0 or scored_count >= _FULL_QUESTION_COUNT:
    return 0.0
scale = (_FULL_QUESTION_COUNT - scored_count) / (_FULL_QUESTION_COUNT - 1)
return round(scale * _MAX_LOW_N_ADJUSTMENT, 4)
```

Result: **n=1 → +0.20, n=2 → +0.1333, n=3 → +0.0667, n≥4 → 0.0** (linear taper). `scored_count=0` also returns `0.0` — `derive_recommendation` already routes an empty question set straight to `"pass"`, not a floored buy/sell.

### Threshold derivation

```python
_BUY_THRESHOLD, _SELL_THRESHOLD = 0.35, -0.35

buy_threshold  = _BUY_THRESHOLD  - asymmetry_adjustment + low_n_adjustment
sell_threshold = _SELL_THRESHOLD - asymmetry_adjustment - low_n_adjustment
```

Both adjustments push in the same direction — buy easier to trigger, sell harder — for different reasons: asymmetry because a convex payoff justifies more mechanical-score risk; low-n because a thin ledger's score is artificially pinned toward ±1 and shouldn't be trusted at the base threshold. They stack (both subtract from `buy_threshold`, both get added-with-a-minus to `sell_threshold`) rather than one replacing the other.

### `clamp_adjustment(delta) -> float`
Coerces to float (`0.0` on `TypeError`/`ValueError`), clamps to `[-0.30, 0.30]` (`_MAX_ADJUSTMENT`) — the LLM's proposed nudge to the mechanical score can never move it further than this, and a malformed value just becomes zero rather than erroring.

### `derive_recommendation(questions, adjusted_score, llm_recommendation, buy_threshold, sell_threshold) -> str`
Empty `questions` → `"pass"` (insufficient scorable signal — distinct from `"hold"`, which means signal exists and nets neutral). If the LLM returned a valid `buy`/`sell`/`hold`/`pass`, use it verbatim. Otherwise fall back to the mechanical threshold mapping against `adjusted_score`.

### What the LLM actually contributes
`run()` computes everything above in code first, then sends the questions, monitor list, risk-judge output, mechanical score, and both adjustments (already applied to the thresholds shown to the model) to the LLM, and asks for exactly three things: (1) a `rationale_quality_score`/`rationale_quality_notes` grade for each sub-question's reasoning, (2) a bounded `adjustment_delta` (±0.30) with `score_adjustment_rationale`, and (3) a `recommendation` with `decision_rationale`. The prompt explicitly tells the model not to re-litigate the asymmetry/low-n shifts themselves — only to factor the already-adjusted thresholds into its recommendation. `adjusted_score = clamp(mechanical_score + clamp_adjustment(delta), -1, 1)`. Nothing about `mechanical_score`, `upside_impact`, `downside_impact`, or the threshold values is LLM-computed — only `adjusted_score`'s *delta* and the final label (when the LLM supplies a valid one) come from the model.

---

## Pipeline Orchestrator

### `forecaster/pipeline.py` — `ForecastPipeline`

| Method | Description |
|---|---|
| `__init__(max_workers=4)` | Thread pool size for parallel stages |
| `run(symbol, question_horizon_days=90, force=False) -> Optional[int]` | Full pipeline. Returns `forecast_id`, or `None` if triage rejects (see [Triage](README.md#triage-the-gate-before-spending-any-money)). `force=True` bypasses triage — manual re-runs / model comparisons only, never the scheduled/batch path |
| `_get_prior_adjusted_score(symbol)` | `SELECT adjusted_score FROM forecasts WHERE symbol=... ORDER BY forecast_date DESC LIMIT 1` — what triage gates on |
| `_get_position_context(symbol)` | Reads thesis/risk/threshold fields from the portfolio DB's `positions` table (separate connection — see [Cross-Repo Dependency](#cross-repo-dependency)) |
| `_insert_partial_forecast(...)` | Inserts a skeleton `forecasts` row; returns the new `id` |
| `_is_equity_like(instrument_type)` | Gates Earnings/PrimarySource — skips FX/currency/future/futures/forward/crypto/fixed-income; unrecognized/blank types default to equity treatment |
| `_run_parallel(callables)` | Runs callables concurrently via `ThreadPoolExecutor`, returns results in submission order |

### Pipeline Execution Order

```
1.  TriageAgent            — reject if |prior adjusted_score| < 0.30 (unless force=True)
    v (pass)
2.  [Insert partial forecasts row] — establishes forecast_id for all FK references
    v
3.  QuestionDefinitionAgent    — decomposes thesis+risks into <=7 sub-questions,
    |                            each inserted into forecast_questions
    v
4.  MacroQAgent                — macro regime tree (live market data)
    v
5.  RiskJudgeAgent              — downside floor + risk density judgment
    v
6a. EarningsAgent      -+
6b. PrimarySourceAgent  -+ (parallel; skipped if not _is_equity_like)
    also: get_technical_context() runs concurrently (non-fatal if it fails)
    v
7a. MomentumAgent -+
7b. TrendAgent    -+ (parallel; whole block skipped if no price data source succeeded)
7c. VolumeAgent   -+
    v
8.  TechnicalJudgeAgent     — synthesizes momentum/trend/volume
    v
9.  For each surviving sub-question, fanned out in parallel (<=7x):
      Elicitation -> Review -> ConfidenceJudge
    v
10. AggregationAgent        — mechanical score + bounded LLM adjustment -> recommendation
```

---

## Scripts

### `scripts/run_migrations.py`
Runs all `migrations/*.sql` files in sorted order against Postgres with autocommit. Idempotent (`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` throughout). No CLI args.

### `scripts/seed_prompt_registry.py`
Reads each `personas/<agent>.md` file and inserts it into `prompt_registry` (`is_active=TRUE`) for any agent that doesn't already have an active prompt. Idempotent — skips agents that already have one. No CLI args.

### `scripts/update_prompt.py`
```
python scripts/update_prompt.py --agent elicitation --version v1.2 --file personas/elicitation.md
```
Deactivates the current active prompt for `--agent` and inserts a new row at `--version` from `--text` or `--file`. Never edit `prompt_registry` in place.

### `scripts/run_macroq.py`
Runs `MacroQAgent().run()` once, standalone (no position needed). Intended for a scheduler (e.g. Windows Task Scheduler) each morning. Exits 1 on error. Does not touch `ForecastPipeline` or triage at all.

### `scripts/run_forecasts.py`
```
python scripts/run_forecasts.py                              # all active positions, triage-gated
python scripts/run_forecasts.py --symbol AAPL                # one position, triage-gated
python scripts/run_forecasts.py --symbol AAPL --force        # one position, triage bypassed
python scripts/run_forecasts.py --symbol AAPL --horizon 60    # override the 90-day default horizon
```
`--force` without `--symbol` is a hard CLI error — bulk triage bypass is refused. Iterates symbols, calls `ForecastPipeline.run(...)`, logs per-symbol success/triage-skip/failure, exits 1 if any symbol raised.

### `scripts/run_resolution.py`
Resolves `forecast_questions` rows with `resolution_source = "price"` where a `$threshold` + direction can be regex-extracted from `resolution_criteria`; computes `brier` and updates `agent_weights` under `agent_id="confidence_judge"`, keyed by that question's own `model_id` and `catalyst`/`risk` type. Any question that isn't `price`-sourced, or is but has no extractable threshold, is logged as needing manual resolution (see the README's [Resolution](README.md#resolution-what-gets-auto-checked-and-what-doesnt) section) — there is no column, table, or report file for this list; it's stdout/log output only, and no script in this repo performs the manual update.

Never writes `mechanical_score` or `adjusted_score` — resolution activity for a symbol has no effect on what a future triage check sees for it.

---

## Tests

| File | Scope |
|---|---|
| `test_agents.py` | Mocked-API unit tests: `extract_json`, `TriageAgent`, `QuestionDefinitionAgent` (incl. the 7-question cap), `MacroQAgent._persist_tree`, `RiskJudgeAgent`, `MomentumAgent`, `TechnicalJudgeAgent`, `ReviewAgent`, `PrimarySourceAgent` (data-source fallback priority), and the bulk of `AggregationAgent`'s formulas (mechanical score, `clamp_adjustment`, `derive_recommendation`, both adjustments) |
| `test_pipeline.py` | `ForecastPipeline._is_equity_like` classification only — full `pipeline.run()` is exercised manually/live, not unit-tested |
| `test_edgar_client.py` | Mocked SEC network calls: CIK lookup/caching, quarterly-financials extraction, filing-form filtering, HTML-stripped excerpts, Form 4 parsing |
| `test_image_extractor.py` | Loads `Technical Analysis/image_extractor.py` by file path (not a package); asserts it extracts at least one image from the reference PDF |
| `test_db.py` | Live-DB integration test against both `investment_forecaster` and `investment_portfolio` — excluded from CI |

Run: `python -m pytest --ignore=tests/test_db.py`

---

## CI

`.github/workflows/ci.yml` — single `test` job on a self-hosted runner, shell `cmd`, triggered on push to `main`/`develop`/`feature/**`/`claude/**` and PRs into `main`/`develop`.

1. `actions/checkout@v4`
2. `pip install -r requirements.txt`
3. `python -m pytest --ignore=tests/test_db.py -v`

The workflow file sets no `env:` block — because the runner is self-hosted (a persistent machine, not an ephemeral container), it relies on `FORECASTER_SECRETS_DIR` (or `config.toml`, though that risks being wiped by `actions/checkout`'s clean step — see `forecaster/config.py`) already being set on that machine to find the real Secrets folder, the same way `PYTHONUTF8` is expected to already be set (see `CLAUDE.md`). Note: CI doesn't run migrations or prompt seeding — it only runs the mocked-API unit tests, most of which still don't touch a live DB even though several import the `forecaster.credentials` chain at module load time (see `TriageAgent`/`AggregationAgent` tests in `test_agents.py`), so a working Secrets lookup is required for collection to succeed even though no test hits Postgres.

---

## Cross-Repo Dependency

`ForecastPipeline._get_position_context()` reads `investment_thesis`, `risks`, `business`, `competitive_landscape`, `financials`, `hold_period`, `hold_period_rationale`, `name`, `label`, `type`, `asymmetric_rating`, `risk_level`, `risk_level_rationale`, `tags`, `source_name`, `source_link`, `profile_change_log`, `profile_confidence`, `profile_rationale`, `profile_model`, `thesis_test_date`, `thesis_list`, `thesis_list_rationale`, and `drawdown_threshold` from the `positions` table in `investment_portfolio`, owned by the sibling repo `investment-portfolio-manager`, via `portfolio_db_cursor()`. Postgres doesn't support cross-database queries, so this is a genuinely separate connection, not a joined query — `run_resolution.py` similarly fetches positions separately and merges in Python.

Run the portfolio-manager's sync first to make sure `positions` is current before running forecasts.

---

## Prompt Management

Prompts are database rows, not code. `personas/<agent>.md` files are the **source of truth for seeding** — read once by `seed_prompt_registry.py` into `prompt_registry`. After that, changes go through `update_prompt.py` (which versions the change) — never edit a `prompt_registry` row in place; always deactivate the old one and insert a new versioned row.

---

## Extension Points

- **Add a new agent:** create `forecaster/agents/my_agent.py` (subclass `BaseAgent`, set `agent_id`, implement `_parse_response()`), create `personas/my_agent.md`, add an entry to `personas/model_config.py`'s `AGENT_MODELS`, add it to `seed_prompt_registry.py`'s agent list, wire it into `pipeline.py`.
- **Add a new migration:** `migrations/NNN_description.sql` with the next sequential number, using `IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS` guards throughout. `run_migrations.py` picks it up automatically.
- **Change a model:** edit `personas/model_config.py`'s `AGENT_MODELS` only; add pricing to `_PRICING` in `base.py` if it's a new model. Never set `model` on the agent class itself.
- **Update a prompt:** edit the `.md` file, then `python scripts/update_prompt.py --agent <agent_id> --version <vX.Y>`.
