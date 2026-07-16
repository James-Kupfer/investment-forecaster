-- investment_forecaster PostgreSQL schema
-- Run this once against a fresh investment_forecaster database:
--   psql -U postgres -d investment_forecaster -f setup/create_schema_postgres.sql
--
-- Create the database first if needed:
--   CREATE DATABASE investment_forecaster;
--   CREATE DATABASE investment_portfolio;   -- for investment-portfolio-manager

CREATE TABLE IF NOT EXISTS prompt_registry (
    id                SERIAL          PRIMARY KEY,
    agent_id          VARCHAR(100)    NOT NULL,
    version           VARCHAR(20),
    prompt_version    VARCHAR(20)     NOT NULL DEFAULT 'v1.0',
    prompt_text       TEXT            NOT NULL,
    is_active         BOOLEAN         NOT NULL DEFAULT FALSE,
    authored_by_model VARCHAR(100),
    created_at        TIMESTAMP       DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS macro_state (
    id                   SERIAL          PRIMARY KEY,
    node_id              VARCHAR(100)    NOT NULL UNIQUE,
    parent_node_id       VARCHAR(100),
    macro_date           DATE            NOT NULL,
    composite_score      DOUBLE PRECISION,
    composite_confidence VARCHAR(20),
    composite_rationale  TEXT,
    rates_signal         VARCHAR(50),
    rates_confidence     VARCHAR(20),
    dxy_signal           VARCHAR(50),
    dxy_confidence       VARCHAR(20),
    vix_signal           VARCHAR(50),
    vix_confidence       VARCHAR(20),
    sector_signal        VARCHAR(50),
    sector_confidence    VARCHAR(20),
    node_rationale       TEXT,
    executing_model      VARCHAR(100),
    prompt_version_id    INTEGER,
    created_at           TIMESTAMP       DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS forecasts (
    id                              SERIAL          PRIMARY KEY,
    symbol                          VARCHAR(20)     NOT NULL,
    forecast_date                   DATE            NOT NULL,
    resolution_date                 DATE,
    -- question definition
    question_def_output             TEXT,
    -- macroq
    macroq_node_id                  VARCHAR(50),
    macroq_p                        NUMERIC(5,4),
    macroq_confidence               VARCHAR(10),
    macroq_rationale                TEXT,
    macroq_output                   TEXT,
    -- risk judge
    invq2_floor                     NUMERIC(5,4),
    risk_judge_confidence           VARCHAR(10),
    risk_judge_rationale            TEXT,
    risk_judge_model                VARCHAR(100),
    risk_judge_prompt_version       INTEGER,
    risk_judge_output               TEXT,
    -- earnings
    earnings_signal                 VARCHAR(200),
    earnings_confidence             VARCHAR(10),
    earnings_rationale              TEXT,
    earnings_model                  VARCHAR(100),
    earnings_prompt_version         INTEGER,
    earnings_output                 TEXT,
    -- primary source
    primary_signal                  VARCHAR(200),
    primary_confidence              VARCHAR(10),
    primary_rationale               TEXT,
    primary_model                   VARCHAR(100),
    primary_prompt_version          INTEGER,
    primary_output                  TEXT,
    -- momentum
    momentum_rsi                    NUMERIC(6,2),
    momentum_macd                   VARCHAR(50),
    momentum_roc                    NUMERIC(6,2),
    momentum_signal                 VARCHAR(50),
    momentum_confidence             VARCHAR(10),
    momentum_rationale              TEXT,
    momentum_model                  VARCHAR(100),
    momentum_prompt_version         INTEGER,
    momentum_output                 TEXT,
    -- trend
    trend_signal                    VARCHAR(50),
    trend_ma_alignment              VARCHAR(200),
    trend_confidence                VARCHAR(10),
    trend_rationale                 TEXT,
    trend_model                     VARCHAR(100),
    trend_prompt_version            INTEGER,
    trend_output                    TEXT,
    -- volume
    volume_signal                   VARCHAR(50),
    volume_confidence               VARCHAR(10),
    volume_rationale                TEXT,
    volume_model                    VARCHAR(100),
    volume_prompt_version           INTEGER,
    volume_output                   TEXT,
    -- pattern (excluded from pipeline but columns retained for future use)
    pattern_signal                  VARCHAR(50),
    pattern_key_level               NUMERIC(12,4),
    pattern_confidence              VARCHAR(10),
    pattern_rationale               TEXT,
    pattern_model                   VARCHAR(100),
    pattern_prompt_version          INTEGER,
    pattern_output                  TEXT,
    -- technical judge
    technical_signal                VARCHAR(50),
    technical_key_level             NUMERIC(12,4),
    technical_confidence            VARCHAR(10),
    technical_rationale             TEXT,
    technical_judge_model           VARCHAR(100),
    technical_judge_prompt_version  INTEGER,
    technical_judge_output          TEXT,
    -- aggregation (final recommendation)
    recommendation                  VARCHAR(20),
    aggregation_output              TEXT,
    -- v2 decomposition pipeline: weighted-EV aggregation over forecast_questions
    mechanical_score                NUMERIC(8,4),
    adjusted_score                  NUMERIC(8,4),
    score_adjustment_rationale      TEXT,
    decision_rationale              TEXT,
    expected_upside_impact          NUMERIC(8,4),
    expected_downside_impact        NUMERIC(8,4),
    upside_downside_ratio           NUMERIC(8,4),
    monitor_list                    TEXT,
    nearterm_critical_high_count    INTEGER,
    scale_adjusted_density_flag     BOOLEAN,
    asymmetry_adjustment            NUMERIC(8,4),
    buy_threshold_used              NUMERIC(8,4),
    sell_threshold_used             NUMERIC(8,4),
    schema_version                  SMALLINT        DEFAULT 1,
    created_at                      TIMESTAMP       DEFAULT NOW()
);

-- forecast_questions: one row per decomposed sub-question (catalyst or risk), v2 pipeline.
-- See C:\Users\james\.claude\plans\i-updated-the-list-wise-pnueli.md for full rationale.
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

CREATE INDEX IF NOT EXISTS idx_forecast_questions_forecast_id ON forecast_questions(forecast_id);
CREATE INDEX IF NOT EXISTS idx_forecast_questions_unresolved ON forecast_questions(resolution_date) WHERE resolved = FALSE;

CREATE TABLE IF NOT EXISTS llm_call_log (
    id                SERIAL          PRIMARY KEY,
    forecast_id       INTEGER,
    macro_state_id    INTEGER,
    agent_id          VARCHAR(100)    NOT NULL,
    prompt_version_id INTEGER,
    executing_model   VARCHAR(100),
    tokens_in         INTEGER         DEFAULT 0,
    tokens_out        INTEGER         DEFAULT 0,
    tokens_cached     INTEGER         DEFAULT 0,
    call_cost_usd     DOUBLE PRECISION,
    duration_ms       INTEGER,
    error             TEXT,
    response_text     TEXT,
    created_at        TIMESTAMP       DEFAULT NOW()
);

-- PK is (agent_id, question_type, model_id) — one accuracy row per agent per question per model
CREATE TABLE IF NOT EXISTS agent_weights (
    agent_id          VARCHAR(100)    NOT NULL,
    question_type     VARCHAR(50)     NOT NULL,
    model_id          VARCHAR(100)    NOT NULL,
    rolling_accuracy  DOUBLE PRECISION,
    sample_size       INTEGER         DEFAULT 0,
    last_updated      TIMESTAMP       DEFAULT NOW(),
    PRIMARY KEY (agent_id, question_type, model_id)
);

CREATE TABLE IF NOT EXISTS position_catalysts (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    catalyst        TEXT            NOT NULL,
    catalyst_date   DATE,
    created_at      TIMESTAMP       DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS position_sources (
    id          SERIAL          PRIMARY KEY,
    symbol      VARCHAR(20)     NOT NULL,
    source_name VARCHAR(200),
    url         VARCHAR(500),
    summary     TEXT,
    created_at  TIMESTAMP       DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_log (
    id                  SERIAL          PRIMARY KEY,
    source              VARCHAR(100)    NOT NULL,
    records_processed   INTEGER         DEFAULT 0,
    records_inserted    INTEGER         DEFAULT 0,
    records_updated     INTEGER         DEFAULT 0,
    records_errors      INTEGER         DEFAULT 0,
    run_at              TIMESTAMP       DEFAULT NOW()
);
