-- Backfills total_evidence / conviction / final_score (added by 014_conviction_scoring.sql)
-- for every historical row that predates that migration. 014 added the columns but never
-- backfilled them, even though every input they need -- adjusted_score, expected_upside_impact,
-- expected_downside_impact -- has existed since 008_decomposition_pipeline.sql, well before
-- conviction scoring shipped. This is not a re-judgment of anything: total_evidence, conviction,
-- and final_score are pure deterministic functions of columns already persisted on the row, using
-- the exact formula AggregationAgent.compute_conviction() applies today (1 - exp(-M/7), M = total
-- weighted evidence). Nothing about `recommendation` itself is touched or recomputed -- that
-- column is the LLM's own verbatim call under whatever thresholds were live at the time and is
-- never retroactively re-derived (see forecaster/agents/aggregation.py: derive_recommendation).
--
-- Once final_score exists for these rows, they also become eligible for the recommendation_band
-- backfill that 015_recommendation_band.sql already ran (its idempotent UPDATE only matched rows
-- that had final_score at the time IT ran, i.e. before this migration existed) -- so this file
-- repeats that same banding UPDATE afterward to pick up everything just backfilled above. See
-- forecaster/agents/aggregation.py: compute_conviction(), derive_recommendation_band().
--
-- Guarded to schema_version = 2 (the only pipeline that ever wrote these three input columns --
-- v1's columns were dropped entirely by 011) even though every existing row already satisfies it.
--
-- Split into two passes rather than one UPDATE computing everything inline: compute_conviction()
-- rounds conviction to 4dp BEFORE run() multiplies it into final_score (aggregation.py:
-- "final_score = round(adjusted_score * conviction, 4)" using the already-rounded conviction, not
-- the raw exp() expression). Folding both into a single UPDATE would re-derive conviction at full
-- numeric precision for the final_score arm, which silently disagrees with the stored (rounded)
-- conviction column by 1 in the last decimal place whenever the rounding boundary falls between
-- them -- verified against forecaster.agents.aggregation.compute_conviction() directly: an inline
-- single-pass version of this migration mismatched final_score on 8 of 79 rows. The second UPDATE
-- below reads back the conviction just written, exactly mirroring what the Python code does.
UPDATE forecasts
SET total_evidence = ROUND((expected_upside_impact + expected_downside_impact)::numeric, 4),
    conviction = CASE
        WHEN (expected_upside_impact + expected_downside_impact) > 0
            THEN ROUND((1 - EXP(-(expected_upside_impact + expected_downside_impact) / 7.0))::numeric, 4)
        ELSE 0.0
    END
WHERE schema_version = 2
  AND final_score IS NULL
  AND adjusted_score IS NOT NULL
  AND expected_upside_impact IS NOT NULL
  AND expected_downside_impact IS NOT NULL;

UPDATE forecasts
SET final_score = ROUND((adjusted_score * conviction)::numeric, 4)
WHERE schema_version = 2
  AND final_score IS NULL
  AND adjusted_score IS NOT NULL
  AND conviction IS NOT NULL;

-- Same banding logic as 015_recommendation_band.sql, repeated here so rows backfilled just above
-- (which did not have final_score when 015 ran) get banded too, in this same migration pass.
UPDATE forecasts
SET recommendation_band = CASE
        WHEN recommendation = 'Buy'  AND final_score >= buy_threshold_used  + 0.20 THEN 'Strong Buy'
        WHEN recommendation = 'Sell' AND final_score <= sell_threshold_used - 0.20 THEN 'Strong Sell'
        ELSE recommendation
    END,
    strong_margin_used = 0.20
WHERE recommendation IS NOT NULL
  AND recommendation_band IS NULL
  AND final_score IS NOT NULL
  AND buy_threshold_used IS NOT NULL
  AND sell_threshold_used IS NOT NULL;
