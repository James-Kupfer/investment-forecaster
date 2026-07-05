# Single source of truth for agent-to-model assignments.
# To swap a model, edit this file only — no agent file needs to change.
AGENT_MODELS: dict[str, str] = {
    # 1. Triage gate: decides whether a position warrants a full forecast run.
    "triage":              "claude-haiku-4-5-20251001",
    # 2. Question definer: converts the investment thesis into a precise, binary, time-bounded forecasting question.
    "question_definition": "claude-haiku-4-5-20251001",
    # 3. Macro analyst: builds a decision tree from VIX, DXY, rates, and sector ETF signals.
    "macroq":              "claude-haiku-4-5-20251001",
    # 4. Risk judge: identifies tail risks and sets the systematic downside floor (invq2_floor).
    "risk_judge":          "claude-haiku-4-5-20251001",
    # 5a. Earnings analyst: assesses earnings trajectory, FCF quality, and beat/miss trend. [parallel]
    "earnings":            "claude-haiku-4-5-20251001",
    # 5b. Primary source analyst: weighs earnings transcripts, filings, and guidance for or against the thesis. [parallel]
    "primary_source":      "claude-haiku-4-5-20251001",
    # 6a. Momentum analyst: interprets RSI and MACD to classify the momentum regime. [parallel]
    "momentum":            "claude-haiku-4-5-20251001",
    # 6b. Trend analyst: evaluates moving-average alignment and ADX to classify the trend regime. [parallel]
    "trend":               "claude-haiku-4-5-20251001",
    # 6c. Volume analyst: determines whether volume confirms or diverges from the prevailing trend. [parallel]
    "volume":              "claude-haiku-4-5-20251001",
    # 6d. Pattern analyst: identifies chart patterns and key price levels from TA context. [parallel]
    "pattern":             "claude-haiku-4-5-20251001",
    # 6e. Technical judge: synthesises momentum, trend, volume, and pattern signals into a single technical verdict.
    "tech_judge":          "claude-haiku-4-5-20251001",
    # 7. Superforecaster: applies inside view, outside view, pre-mortem, and reference class to produce an initial probability.
    "elicitation":         "claude-haiku-4-5-20251001",
    # 8. Bias reviewer: checks the elicitation output for overconfidence, anchoring, or missing evidence.
    "review":              "claude-haiku-4-5-20251001",
    # 9. Probability calibrator: applies shrinkage, confidence intervals, and sizing haircut to the elicited estimate.
    "confidence_judge":    "claude-haiku-4-5-20251001",
    # 10. Final synthesiser: merges all agent outputs into upside/downside probabilities and a committee summary.
    "aggregation":         "claude-haiku-4-5-20251001",
}
