-- Drops the retired v1 single-question forecasting columns from `forecasts`.
-- The v2 decomposition pipeline (forecast_questions) has been the only pipeline
-- that writes to `forecasts` since migration 008 — schema_version=2 is set
-- unconditionally by AggregationAgent, and no code path anywhere in forecaster/
-- writes invq1_*/invq2_*/invq3_* or any of the columns below. Historical v1
-- rows and the run_resolution.py legacy pass that resolved them are retired
-- (see CLAUDE.md / architecture.md).
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_definition;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_definition_confidence;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_definition_rationale;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_def_model;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_def_prompt_version;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_p;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_confidence;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_rationale;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_model;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq3_prompt_version;
ALTER TABLE forecasts DROP COLUMN IF EXISTS elicitation_output;
ALTER TABLE forecasts DROP COLUMN IF EXISTS review_flag;
ALTER TABLE forecasts DROP COLUMN IF EXISTS review_rationale;
ALTER TABLE forecasts DROP COLUMN IF EXISTS review_confidence;
ALTER TABLE forecasts DROP COLUMN IF EXISTS review_model;
ALTER TABLE forecasts DROP COLUMN IF EXISTS review_prompt_version;
ALTER TABLE forecasts DROP COLUMN IF EXISTS review_output;
ALTER TABLE forecasts DROP COLUMN IF EXISTS base_case_p;
ALTER TABLE forecasts DROP COLUMN IF EXISTS ci_low;
ALTER TABLE forecasts DROP COLUMN IF EXISTS ci_high;
ALTER TABLE forecasts DROP COLUMN IF EXISTS sizing_haircut;
ALTER TABLE forecasts DROP COLUMN IF EXISTS confidence_rationale;
ALTER TABLE forecasts DROP COLUMN IF EXISTS confidence_confidence;
ALTER TABLE forecasts DROP COLUMN IF EXISTS confidence_judge_model;
ALTER TABLE forecasts DROP COLUMN IF EXISTS confidence_prompt_version;
ALTER TABLE forecasts DROP COLUMN IF EXISTS confidence_judge_output;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq1_p;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq1_confidence;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq1_rationale;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq1_model;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq1_prompt_version;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq2_p;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq2_confidence;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq2_rationale;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq2_model;
ALTER TABLE forecasts DROP COLUMN IF EXISTS invq2_prompt_version;
ALTER TABLE forecasts DROP COLUMN IF EXISTS compound_conviction;
ALTER TABLE forecasts DROP COLUMN IF EXISTS asymmetry_ratio;
ALTER TABLE forecasts DROP COLUMN IF EXISTS resolved;
ALTER TABLE forecasts DROP COLUMN IF EXISTS resolved_outcome;
ALTER TABLE forecasts DROP COLUMN IF EXISTS brier_q1;
ALTER TABLE forecasts DROP COLUMN IF EXISTS brier_q2;
ALTER TABLE forecasts DROP COLUMN IF EXISTS brier_q3;
