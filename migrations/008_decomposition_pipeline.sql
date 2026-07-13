-- Thesis/risk decomposition pipeline (v2.0): sub-question fan-out + weighted-EV aggregation.
-- Legacy invq1_*/invq2_*/invq3_*/compound_conviction/asymmetry_ratio are retained nullable
-- for historical rows and the old run_resolution.py path — the new pipeline never writes them.
-- See C:\Users\james\.claude\plans\i-updated-the-list-wise-pnueli.md for full rationale.

ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS mechanical_score NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS adjusted_score NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS score_adjustment_rationale TEXT;
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS decision_rationale TEXT;
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS expected_upside_impact NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS expected_downside_impact NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS upside_downside_ratio NUMERIC(8,4);
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS monitor_list TEXT;
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS nearterm_critical_high_count INTEGER;
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS scale_adjusted_density_flag BOOLEAN;
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS schema_version SMALLINT DEFAULT 1;

CREATE TABLE IF NOT EXISTS forecast_questions (
    id                      SERIAL          PRIMARY KEY,
    forecast_id             INTEGER         NOT NULL REFERENCES forecasts(id),
    question_type           VARCHAR(20)     NOT NULL,
    question_text           TEXT            NOT NULL,
    resolution_criteria      TEXT,
    resolution_date          DATE,
    resolution_source        VARCHAR(20),
    evidence_source          VARCHAR(20),
    impact_direction         VARCHAR(1),
    impact_magnitude         VARCHAR(20),
    decomposition_rationale  TEXT,
    elicitation_p            NUMERIC(5,4),
    review_flag              BOOLEAN,
    review_rationale         TEXT,
    final_probability        NUMERIC(5,4),
    confidence               VARCHAR(10),
    model_id                 VARCHAR(100),
    forecast_rationale       TEXT,
    rationale_quality_score  NUMERIC(5,4),
    rationale_quality_notes  TEXT,
    question_output          TEXT,
    resolved                 BOOLEAN         NOT NULL DEFAULT FALSE,
    resolved_outcome         TEXT,
    brier                    NUMERIC(8,6),
    created_at               TIMESTAMP       DEFAULT NOW()
);

-- Belt-and-suspenders for the case where this migration already ran once
-- (CREATE TABLE IF NOT EXISTS above is a no-op against an existing table).
ALTER TABLE forecast_questions ADD COLUMN IF NOT EXISTS model_id VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_forecast_questions_forecast_id ON forecast_questions(forecast_id);
CREATE INDEX IF NOT EXISTS idx_forecast_questions_unresolved ON forecast_questions(resolution_date) WHERE resolved = FALSE;
