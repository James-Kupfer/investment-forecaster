-- Conviction-scaled scoring (aggregation.py). compute_mechanical_score's
-- normalization ((up-down)/(up+down)) preserves only direction / one-sidedness,
-- not magnitude, so a thin ledger pins the score to +/-1 regardless of how little
-- total evidence backs it. The decision now scales that normalized tilt by a
-- saturating conviction multiplier -- conviction = 1 - exp(-M/k), where
-- M = total weighted evidence (expected upside + downside impact) -- to form
-- final_score, and Passes any position whose M is below a floor (insufficient
-- signal to act, distinct from a neutral Hold). These three values are persisted
-- so the k / M_FLOOR priors can be calibrated against realized position outcomes
-- later. See forecaster/agents/aggregation.py: compute_conviction() and
-- derive_recommendation().
--
-- Replaces the low-n threshold widening from 010: a thin ledger now attenuates the
-- score directly (via conviction) instead of widening the buy/sell bar, so
-- low_n_adjustment is dropped. question_count (also added in 010) is retained.
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS total_evidence NUMERIC(10,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS conviction NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS final_score NUMERIC(8,4);
ALTER TABLE forecasts DROP COLUMN IF EXISTS low_n_adjustment;
