-- Granular recommendation band (aggregation.py). recommendation carries one of four
-- flat labels (Buy/Sell/Hold/Pass), but final_score underneath it is continuous in
-- [-1, +1] and is already compared against per-position buy_threshold_used /
-- sell_threshold_used -- so the row already knows HOW STRONG a Buy is, it was just
-- being discarded at the last step. recommendation_band splits Buy and Sell by how far
-- final_score cleared the effective threshold, giving Strong Buy / Buy / Hold / Sell /
-- Strong Sell / Pass for display. Hold and Pass are not split (there is no
-- "Strong Hold").
--
-- The band is derived from the STORED recommendation, not from final_score directly.
-- derive_recommendation returns the LLM's own label verbatim when valid, so
-- recommendation and final_score can legitimately disagree (forecast 30 / FNV: the
-- model answered HOLD on a score that cleared the buy bar, calling the margin "within
-- measurement error"). Banding off final_score alone would contradict the stored call
-- on exactly those rows, so the band only ever refines it -- and a NULL recommendation
-- yields a NULL band, since there is no call to refine. Nothing here is LLM-computed --
-- this is a deterministic presentation layer over values already persisted.
--
-- strong_margin_used pins the margin that was in effect for the run, for the same
-- reason buy_threshold_used / sell_threshold_used / asymmetry_adjustment already are:
-- the margin is an uncalibrated prior, and storing it per-row means it can be retuned
-- later and historical bands recomputed in SQL without re-running any forecast.
--
-- See forecaster/agents/aggregation.py: derive_recommendation_band().
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS recommendation_band VARCHAR(20);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS strong_margin_used NUMERIC(8,4);

-- Backfill. Every input is already persisted, so rows from 014 onward (the migration
-- that introduced final_score) can be banded retroactively. Earlier rows have no
-- final_score and are correctly left NULL by the guards rather than guessed at.
-- Idempotent via "recommendation_band IS NULL" -- a second run matches nothing.
--
-- The 0.20 margin is deliberately hardcoded rather than kept in sync with
-- aggregation.py's _STRONG_MARGIN: a migration is a historical record of what was
-- actually applied, and must not silently change meaning if that prior is retuned.
-- strong_margin_used below records that these rows were banded at 0.20.
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
