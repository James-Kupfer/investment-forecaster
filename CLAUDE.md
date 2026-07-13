# investment-forecaster

LLM Superforecaster — applies Tetlock superforecaster discipline to investment positions.

> For full schema, module/function reference, and agent catalogue see `architecture.md`.

## Pipeline architecture (v2 — decomposition)
- A position's thesis + risks are decomposed (`question_definition`) into up to 7 independently
  forecast Critical/High-impact sub-questions (catalysts = positive price impact if YES, risks =
  negative), each stored as a `forecast_questions` row. Long/short is never assigned upstream —
  buy/sell/hold/pass is derived downstream by `aggregation` from the net weighted-EV of all
  sub-question outcomes.
- `pipeline.py` runs four stages: A) decompose once, B) gather shared symbol-level evidence once
  (macro/risk/earnings/primary_source/technical), C) forecast each sub-question independently
  (elicitation → review → confidence_judge, fanned out in parallel), D) aggregate once into a
  recommendation.
- The mechanical expected-value score (`mechanical_score`, `expected_upside_impact`,
  `expected_downside_impact`, `upside_downside_ratio`) is always computed deterministically in
  `aggregation.py` — never by the LLM. The LLM's role is bounded to grading each sub-question's
  rationale quality (`rationale_quality_score`/`rationale_quality_notes`) and proposing a capped
  ±0.30 adjustment with a logged reason (`score_adjustment_rationale`) — it never silently
  replaces the mechanical score. Both are stored so calibration review can tell which is better.
- **Risk/reward asymmetry scales the buy/sell thresholds**, mechanically, in `aggregation.py`
  (`compute_asymmetry_adjustment`): `positions.asymmetric_rating` (High/Medium/Low/No, from the
  investment-profile skill, rating the plausible ~1-year return path as High=10x, Medium>=5x,
  Low>=1x, else No) shifts both `buy_threshold` and `sell_threshold` toward more risk tolerance —
  buy gets easier to trigger, sell gets harder (don't dump a moonshot candidate on one bad print).
  The adjustment is derived directly from those floor multiples scaled against "High" (10x);
  missing/"No"/unrecognized ratings apply no shift. Shift is capped at ±0.20 and logged to
  `asymmetry_adjustment`/`buy_threshold_used`/`sell_threshold_used` on `forecasts` for audit —
  never a silent change to the recommendation logic. `positions.asymmetric_rating` supersedes the
  old `is_asymmetric` BOOLEAN column, whose boolean coercion in the portfolio-manager's
  `excel_sync.py` had been silently collapsing every real rating (including "No") to `false` —
  see `investment-portfolio-manager` migration 006.
- **Resolution limitation, by design**: sub-questions framed around a specific reported metric
  (`resolution_source = filing`) forecast more accurately than a generic price bet, but
  `run_resolution.py` cannot auto-resolve them — that requires reading an actual filing/press
  release. Only `price`-sourced sub-questions (rare — mainly the no-thesis fallback path)
  auto-resolve via yfinance. Filing/manual sub-questions are surfaced in a "needs manual
  resolution" log report, not silently skipped or guessed. See
  `C:\Users\james\.claude\plans\i-updated-the-list-wise-pnueli.md` for the full rationale.
- Legacy v1 single-question columns (`invq1_*`, `invq2_*`, `invq3_*`, `compound_conviction`,
  `asymmetry_ratio`) are retained nullable on `forecasts` for historical rows only —
  `run_resolution.py` still resolves old unresolved v1 rows via its legacy pass, but the v2
  pipeline never writes these columns. `schema_version` on `forecasts` disambiguates a row's era.

## External data sources
- `forecaster/edgar_client.py` fetches real data from SEC EDGAR for `earnings` (quarterly EPS/net
  income/operating cash flow/capex/revenue via XBRL company facts) and `primary_source` (10-K/10-Q/
  20-F/8-K/6-K filing excerpts, Form 4 open-market insider buy/sell transactions). Both agents fall
  back to the position's free-text `financials` field or the model's training knowledge when a
  symbol has no EDGAR CIK match (common for foreign-private-issuer filers), and label the fallback
  via a `data_source` field passed into the prompt so rationale stays honest about provenance.
- EDGAR does **not** provide consensus EPS estimates, management guidance, earnings call
  transcripts, investor presentations, or short interest — no free source substitutes these. The
  `earnings.md`/`primary_source.md` prompts treat their absence as the structural norm (pinning the
  relevant sub-signals to neutral/unavailable) rather than something to fill in from training
  knowledge.
- Requires `SEC_EDGAR_USER_AGENT` env var (see `.env.example`) — SEC's fair-access policy requires a
  descriptive User-Agent with a real contact email; missing/generic values risk throttling.

## Database
- PostgreSQL on `localhost:5432`
- **`investment_forecaster`** — this app's database (`db_cursor()` / `get_connection()`)
- **`investment_portfolio`** — owned by `investment-portfolio-manager`; read via `portfolio_db_cursor()` / `get_portfolio_connection()` in `forecaster/db.py`
- Connection via `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` env vars (see `.env.example`)
- **Credentials go in `.env` only — never in code or committed config**
- Cross-database queries not supported in PostgreSQL; `run_resolution.py` fetches positions separately via `portfolio_db_cursor()` and merges in Python

## Agent Conventions
- All LLM-calling agents subclass `BaseAgent` (`forecaster/agents/base.py`); set `agent_id` as a class attribute and implement `_parse_response()`. Do NOT set `model` on the agent class — `forecaster/agents/model_config.py`'s `AGENT_MODELS` is the sole owner; `BaseAgent.__init__` raises if `agent_id` isn't listed there.
- Every agent's `_parse_response()` must extract text via `self.extract_text_block(response)`, never `response.content[0].text` directly — models with extended thinking enabled (e.g. `claude-sonnet-5`) return a `ThinkingBlock` first, which has no `.text` attribute.
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
- Mock Anthropic API in unit tests (`unittest.mock.patch`) — `test_db.py` runs against live Postgres, run manually or via scheduled workflow

## Environment
Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` and Postgres credentials (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`).

**`PYTHONUTF8=1` must be set as a real OS/user environment variable (not just in `.env`)** on Windows before running anything that calls the Anthropic API. Without it, this environment's default locale is `cp1252`, and Claude's responses containing em-dashes/smart quotes/other non-ASCII characters get silently corrupted (UTF-8 bytes decoded as cp1252) before they're ever written to `llm_call_log`/`forecasts`/`forecast_questions` — the corruption is baked into the stored text, not just a display artifact, and isn't retroactively fixable except by re-running the affected forecast. `.env`-loaded variables apply too late (after the interpreter has already started with the wrong encoding mode), so this must be `setx PYTHONUTF8 1` (persists for new sessions) or set for the current session before invoking `python`. Verify with `python -c "import locale; print(locale.getpreferredencoding())"` — it must print `utf-8`, not `cp1252`.
