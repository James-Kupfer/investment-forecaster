-- Gives ElicitationAgent and ReviewAgent their own output column instead of
-- both overwriting the shared forecast_questions.question_output (which only
-- ever preserves the LAST writer's blob -- ConfidenceJudgeAgent's). Needed so
-- ForecastPipeline.resume() can reconstruct a fully-completed sub-question's
-- per-stage narrative (not just its scalar elicitation_p/review_flag columns)
-- without a permanent fidelity loss. confidence_judge.py keeps writing
-- question_output as the terminal/"final" blob -- unchanged.
ALTER TABLE forecast_questions ADD COLUMN IF NOT EXISTS elicitation_output TEXT;
ALTER TABLE forecast_questions ADD COLUMN IF NOT EXISTS review_output TEXT;
