-- Position-level risk/reward asymmetry now scales the aggregation buy/sell thresholds.
-- A position that can move 10x in a year justifies accepting more mechanical-score risk
-- than one with a capped/linear payoff of the same probability profile — Kelly-style
-- reasoning (probability x magnitude, not just probability x qualitative severity tier).
-- See forecaster/agents/aggregation.py: compute_asymmetry_adjustment().
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS asymmetry_adjustment NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS buy_threshold_used NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS sell_threshold_used NUMERIC(8,4);
