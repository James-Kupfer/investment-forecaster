-- A position decomposed into very few sub-questions (n=1 especially) pins
-- compute_mechanical_score's normalization to the +/-1 floor/ceiling regardless
-- of that question's actual probability, since there's no second question on
-- the other side of the ledger to counterbalance it. The signal is still real
-- and worth keeping, but the buy/sell thresholds widen (more risk-tolerant
-- toward "hold") as question count drops, tapering back to the base thresholds
-- once decomposition produces a fuller set. See
-- forecaster/agents/aggregation.py: compute_low_n_adjustment().
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS question_count INTEGER;
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS low_n_adjustment NUMERIC(8,4);
