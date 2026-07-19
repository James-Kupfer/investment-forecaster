-- Promotes aggregation's confidence rating to a first-class forecasts column
-- instead of a Power-Query-side dig into aggregation_output's JSON. Backfills
-- existing rows from that same JSON, and Proper-Cases both confidence and
-- recommendation for the rows written before AggregationAgent's schema/persona
-- were changed to emit Proper Case directly (see personas/aggregation.md v2.6
-- and AGGREGATION_SCHEMA/_VALID_RECOMMENDATIONS in aggregation.py). Both
-- UPDATEs are idempotent (INITCAP of an already-proper string is a no-op).
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS confidence VARCHAR(10);

UPDATE forecasts
SET confidence = INITCAP(aggregation_output::json ->> 'confidence')
WHERE confidence IS NULL
  AND aggregation_output IS NOT NULL
  AND aggregation_output::json ->> 'confidence' IS NOT NULL;

UPDATE forecasts
SET recommendation = INITCAP(recommendation)
WHERE recommendation IS NOT NULL
  AND recommendation <> INITCAP(recommendation);
