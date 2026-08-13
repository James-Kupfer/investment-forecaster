# Changelog

Notable changes to the forecasting pipeline and its schema. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), adapted for this project: there are no version
tags or releases, so entries are dated and, where a change touched the schema, cross-referenced to
its `migrations/NNN_*.sql` file — that migration number is the closest thing this repo has to a
version number. See [`architecture.md`](architecture.md) for the current state of the schema and
agent catalogue; this file is the history of how it got there, not a restatement of it.

## [Unreleased]

### Added
- `forecasts.recommendation_band` — a finer-grained display label (**Strong Buy / Buy / Hold /
  Sell / Strong Sell / Pass**) derived deterministically in code from `recommendation` and how far
  `final_score` cleared the position's effective threshold. It is strictly subordinate to
  `recommendation`: it refines the LLM's stored call, never re-derives or overrides it, so a `Hold`
  issued on a score that technically clears the buy bar (as happened on forecast 30/FNV) stays
  `Hold`. `forecasts.strong_margin_used` pins the margin (`_STRONG_MARGIN = 0.20`, an uncalibrated
  prior like `_K_CONVICTION`/`_M_FLOOR`) that was in effect for that run. No prompt or LLM schema
  change. `migrations/015_recommendation_band.sql`. See
  [`architecture.md`](architecture.md#aggregation--from-score-to-recommendation).
- README "Reading results back out" section with the SQL to pull a symbol's latest recommendation
  (with rationale) and its underlying sub-question forecasts — the first documented read path this
  project has had; previously the only way to see a finished forecast was ad hoc SQL.
- `forecasts.decision_summary` — a plain-English sibling to `decision_rationale`, written by the same
  `AggregationAgent` call (no extra API cost or latency). `decision_rationale` is deliberately
  technical, naming internal machinery by name (`mechanical_score`, `invq2_floor`, `conviction`,
  question indices), because it's the audit trail behind the two numeric scores that get
  independently Brier-scored for calibration review — it stays exactly as-is. `decision_summary` is
  additive: a few paragraphs of investment commentary for an experienced investor with no visibility
  into this system's internals, explicitly instructed to translate the finished call rather than
  reword `decision_rationale` with the jargon swapped out. Token-budget recheck done per CLAUDE.md's
  "Token budgets" section: `max_tokens=32000` has ample headroom for the added ~600-1600 tokens, left
  unchanged. Deliberately **not backfilled** — unlike the `total_evidence`/`conviction`/`final_score`
  backfill above, this can't be reconstructed from already-persisted columns; producing it for the
  ~79 existing forecasts would mean a fresh LLM call per historical row, real spend that was
  explicitly deferred rather than attempted quietly. Those rows stay `NULL` until naturally re-run.
  The persona wording (`personas/aggregation.md` v2.72) is a first pass, expected to be iterated on
  once real output can be reviewed. `migrations/017_decision_summary.sql`. See
  [`architecture.md`](architecture.md#aggregation--from-score-to-recommendation) (subsection
  "decision_summary — the same call's plain-English sibling").

### Fixed
- Backfilled `total_evidence`/`conviction`/`final_score` for the 74 historical forecasts that
  predate `014_conviction_scoring.sql` (2026-07-19/20). Those columns didn't exist when those
  forecasts ran, but every input they need — `adjusted_score`, `expected_upside_impact`,
  `expected_downside_impact` — has existed since `008_decomposition_pipeline.sql`, so 014 could
  have backfilled them at the time and simply didn't. This backfills them now, using the same
  formula `compute_conviction()` applies today; `recommendation` itself is untouched — it's the
  LLM's verbatim call and is never retroactively re-derived. Closed the gap this left in
  `recommendation_band` as a side effect: those 74 rows are now bandable too. All 79 recommended
  forecasts verified by independently recomputing `total_evidence`/`conviction`/`final_score`/
  `recommendation_band` in Python and diffing against the stored values — zero mismatches.
  `migrations/016_backfill_conviction_scoring.sql`.
- `architecture.md`'s schema section claimed to reflect migrations through 010 and called
  `setup/create_schema_postgres.sql` an equivalent copy; neither was true (last regenerated at 009,
  missing every column added by 010/012/013/014). Corrected and flagged the setup script as
  bootstrap-only, not runtime- or test-referenced.

## 2026-07-20 — Conviction-scaled scoring (`migrations/014_conviction_scoring.sql`)

`compute_mechanical_score`'s normalization (`(upside - downside) / (upside + downside)`) preserves
direction but discards magnitude, so a thin decomposition (few scorable sub-questions) pins the
score to `±1` regardless of how little evidence backs it. Replaced the old fix for this
(`low_n_adjustment`, migration 010 — widening the buy/sell thresholds as question count dropped)
with a saturating **conviction multiplier**, `1 − exp(−M/k)` where `M` is total weighted evidence,
applied directly to the score: `final_score = (mechanical_score + adjustment_delta) × conviction`.
A thin ledger now attenuates toward `Hold` instead of moving the bar, and a position whose total
evidence falls below a floor (`_M_FLOOR`) is `Pass` outright. Added `total_evidence`, `conviction`,
`final_score`; dropped `low_n_adjustment`. Same commit deterministically enforced the
question-definition admission gate (previously an LLM-followed instruction, now code-checked).

## 2026-07-19 — Confidence promoted to a column, Proper Case (`migrations/013_forecast_confidence_column.sql`)

`forecasts.confidence` was previously only reachable by digging into `aggregation_output`'s JSON
blob from the reporting side (Power Query). Promoted to a first-class `VARCHAR(10)` column, with an
idempotent backfill from the existing JSON. Also normalized `confidence` and `recommendation` to
Proper Case (`Buy` not `buy`) for rows written before the persona/schema were changed to emit that
case directly.

## 2026-07-19 — Mid-pipeline resume (`migrations/012_forecast_questions_stage_outputs.sql`)

Split `forecast_questions.question_output` — previously overwritten in turn by
`ElicitationAgent`, `ReviewAgent`, and `ConfidenceJudgeAgent`, so only the last writer's blob
survived — into separate `elicitation_output`/`review_output` columns. Needed so
`ForecastPipeline.resume()` can reconstruct a fully-completed sub-question's per-stage narrative
after an interrupted run, not just its scalar `elicitation_p`/`review_flag` columns.

## 2026-07-16 — Retired v1 forecasting columns (`migrations/011_drop_legacy_v1_columns.sql`)

Dropped the single-question v1 forecasting columns (`invq1_*`/`invq2_*`/`invq3_*`,
`compound_conviction`, `asymmetry_ratio`, and the v1 resolution columns) from `forecasts`. The v2
decomposition pipeline (`forecast_questions`, introduced 008) had been the only pipeline writing to
`forecasts` since migration 008; nothing in `forecaster/` had written these columns since.

## 2026-07-14 — Low-question-count threshold widening (`migrations/010_low_n_adjustment.sql`)

First fix for the thin-decomposition pinning problem later replaced by conviction scoring (014):
widened the buy/sell thresholds as scored question count dropped, tapering back to the base
thresholds once decomposition produced a fuller set. Added `question_count`, `low_n_adjustment`
(the latter dropped by 014).

## 2026-07-13 — Decomposition pipeline v2.0 (`migrations/008_decomposition_pipeline.sql`, `migrations/009_asymmetry_adjustment.sql`)

The pipeline revamp this project's current architecture is built on. Replaced single-question v1
forecasting with thesis/risk decomposition into up to seven independently-forecast catalyst/risk
sub-questions (new `forecast_questions` table), each run through an elicitation → review →
confidence-judge chain, then aggregated by a deterministic, code-computed expected-value score
(`mechanical_score`) that the LLM may only nudge within a capped ±0.30 (`adjustment_delta`),
never replace. Same change added `compute_asymmetry_adjustment`: a position rated for a plausible
multibagger return (`positions.asymmetric_rating`) gets shifted, more risk-tolerant buy/sell
thresholds, since a convex payoff justifies accepting more mechanical-score risk than a
capped/linear one at the same probability profile.
