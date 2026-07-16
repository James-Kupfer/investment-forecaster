# investment-forecaster

LLM Superforecaster — applies Tetlock superforecaster discipline to investment positions.

> This file is operating instructions for AI coding assistants working in this repo — conventions,
> gotchas, and rules that aren't obvious from reading the code. It is not an introduction to the
> project. **For what the system does, how triage works, and how to run it, see `README.md`. For
> the full database schema, agent catalogue, and module/function reference, see `architecture.md`.**
> Read those first if you need context; this file assumes you already have it.

## Non-negotiable rules
- **The mechanical expected-value score is always computed deterministically in code**
  (`aggregation.py`'s `compute_mechanical_score`) — never by the LLM. The LLM's role is bounded to
  grading each sub-question's rationale quality and proposing a capped ±0.30 adjustment with a
  logged reason (`score_adjustment_rationale`) — it must never silently replace the mechanical
  score. Both are stored (`mechanical_score` vs `adjusted_score`) so calibration review can tell
  which one was right. See `architecture.md#aggregation--from-score-to-recommendation` for the
  exact formulas before touching this file.
- **`positions.asymmetric_rating` (High/Medium/Low/No) is the only source for the asymmetry
  adjustment** — it supersedes the old `is_asymmetric` BOOLEAN column, whose boolean coercion in
  the portfolio-manager's `excel_sync.py` had been silently collapsing every real rating (including
  "No") to `false` (see `investment-portfolio-manager` migration 006). Don't reintroduce a
  boolean-coerced read path for this field.
- **Filing/manual-sourced sub-questions (`resolution_source != "price"`) are never
  auto-resolved or guessed** — `run_resolution.py` logs them as needing manual resolution and
  stops there. Don't "fix" this by inventing a heuristic resolution for filing-anchored questions;
  the whole point is that they need an actual filing read.
- **Never edit a `prompt_registry` row in place** — deactivate the old one, insert a new versioned
  row. `update_prompt.py` enforces this; don't bypass it with direct SQL.
- **Credentials go in the shared `Secrets` folder only — never in `.env`, code, or committed
  config.** `Secrets` is shared across repos specifically to avoid every repo duplicating the same
  password/API key.

## Agent Conventions
- All LLM-calling agents subclass `BaseAgent` (`forecaster/agents/base.py`); set `agent_id` as a class attribute and implement `_parse_response()`. Do NOT set `model` on the agent class — `personas/model_config.py`'s `AGENT_MODELS` is the sole owner; `BaseAgent.__init__` raises if `agent_id` isn't listed there.
- Every agent's `_parse_response()` must extract text via `self.extract_text_block(response)`, never `response.content[0].text` directly — models with extended thinking enabled (e.g. `claude-sonnet-5`) return a `ThinkingBlock` first, which has no `.text` attribute.
- `log_call()` must be called immediately after every API call — never batched; call failures must still be logged.
- When an agent's evidence source can fall back (EDGAR miss → free-text `financials` field → training knowledge, e.g. `earnings.py`/`primary_source.py`), always label which one was used via a `data_source` field in the prompt/output — don't let a fallback masquerade as primary evidence in the stored rationale.

## Prompt Registry
- Prompts live in the DB, not in code. Source of truth for seeding: `personas/<agent>.md` files.
- Update via `python scripts/update_prompt.py --agent <agent_id> --version <vX.Y>`.
- Version format: `v1.0`, `v1.1`, etc.; `authored_by_model` records which model wrote it.

## Migrations
- Files: `migrations/NNN_description.sql` (zero-padded three-digit prefix).
- Always use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` patterns — runner is idempotent.
- Runner: `python scripts/run_migrations.py`.

## Token budgets
- Every agent's `max_tokens` is set generously above any observed real usage — truncation is a
  silent-failure mode, not a loud one: `extract_json` returns whatever complete JSON object it can
  find, so a cut-off response either loses just the fields after the cutoff (if an earlier complete
  object exists) or returns `{}` entirely (if nothing closes). Two agents (`risk_judge`,
  `aggregation`) were caught truncating mid-response on real LIN runs before their budgets were
  raised — one of them (`risk_judge`) had no recoverable earlier draft and silently lost its entire
  output for that run.
- Agents on `claude-sonnet-5`/`claude-opus-4-8` (`question_definition`, `macroq`, `risk_judge`,
  `elicitation`, `review`, `aggregation` as currently configured) need extra headroom: no `thinking`
  param is set in `BaseAgent.call()`, so any extended-reasoning tokens these models produce draw
  from the same `max_tokens` pool as the visible output, not a separate budget.
- Opus was also observed, on the same live run, drafting a full JSON object, writing a
  self-correcting narrative aside ("...correcting to the required schema:"), then emitting a
  second complete object — effectively doubling total output tokens for a single call.
  `extract_json` (`forecaster/utils.py`) handles this by preferring the last successfully-parsed
  top-level object, not the first, but the token budget still has to cover both attempts.
- If you change a prompt to ask for more detail (a new field, a longer rationale requirement),
  re-check `max_tokens` for that agent — don't assume the existing budget still has headroom.

## Development Workflow
- Branch: `develop` for integration, `feature/` or `claude/` for development.
- CI: GitHub Actions self-hosted runner on `JAMES-DESKTOP` (runner: `desktop-forecaster`), shell: `cmd` — runs unit tests only (`--ignore=tests/test_db.py`).
- Mock Anthropic API in unit tests (`unittest.mock.patch`) — `test_db.py` runs against live Postgres, run manually or via scheduled workflow.

## Environment
No `.env` file is used for secrets — see `README.md`'s "Configuration"/"Credentials" sections for
the full setup walkthrough. `config.toml` (git-ignored; copy from `config.example.toml`) is the
first choice for local config — its `[secrets] override` is what `forecaster/config.py` exposes as
`SECRETS_DIRS`, which `forecaster/credentials.py` searches for `Anthropic.py`/`postgres.py`/`SEC.py`
(or their CI-runner-account fallback names) to read `ANTHROPIC_API_KEY`, Postgres credentials
(`DB_HOST`, `DB_USER`, `DB_PASSWORD`), and `SEC_EDGAR_USER_AGENT`. Never hardcode a real secrets
path back into `forecaster/config.py` itself — that's exactly what moving it to a git-ignored
`config.toml` was for. `FORECASTER_SECRETS_DIR` (real OS env var) overrides `config.toml` when set,
ahead of it — this is what the self-hosted CI runner uses, since a git-ignored `config.toml` in its
working directory would get wiped by `actions/checkout`'s clean step between runs. `.env.example`
documents the remaining optional non-secret overrides (`DB_PORT`, `DB_NAME`, `PORTFOLIO_DB_NAME`,
`IBKR_GATEWAY_URL`); set those as real OS env vars if you need to override a `config.toml` value
without editing it.

**`PYTHONUTF8=1` must be set as a real OS/user environment variable** on Windows before running anything that calls the Anthropic API. Without it, this environment's default locale is `cp1252`, and Claude's responses containing em-dashes/smart quotes/other non-ASCII characters get silently corrupted (UTF-8 bytes decoded as cp1252) before they're ever written to `llm_call_log`/`forecasts`/`forecast_questions` — the corruption is baked into the stored text, not just a display artifact, and isn't retroactively fixable except by re-running the affected forecast. This must be `setx PYTHONUTF8 1` (persists for new sessions) or set for the current session before invoking `python`. Verify with `python -c "import locale; print(locale.getpreferredencoding())"` — it must print `utf-8`, not `cp1252`.
