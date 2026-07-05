# Single source of truth for agent-to-model assignments.
# To swap a model, edit this file only — no agent file needs to change.
AGENT_MODELS: dict[str, str] = {
    "aggregation":         "claude-haiku-4-5-20251001",
    "confidence_judge":    "claude-haiku-4-5-20251001",
    "earnings":            "claude-haiku-4-5-20251001",
    "elicitation":         "claude-haiku-4-5-20251001",
    "macroq":              "claude-haiku-4-5-20251001",
    "momentum":            "claude-haiku-4-5-20251001",
    "pattern":             "claude-haiku-4-5-20251001",
    "primary_source":      "claude-haiku-4-5-20251001",
    "question_definition": "claude-haiku-4-5-20251001",
    "review":              "claude-haiku-4-5-20251001",
    "risk_judge":          "claude-haiku-4-5-20251001",
    "tech_judge":          "claude-haiku-4-5-20251001",
    "trend":               "claude-haiku-4-5-20251001",
    "triage":              "claude-haiku-4-5-20251001",
    "volume":              "claude-haiku-4-5-20251001",
}
