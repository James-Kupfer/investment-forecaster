# Single source of truth for agent-to-model assignments. Every LLM-calling
# agent's model comes from here ONLY — individual agent files declare no
# model default of their own (BaseAgent.__init__ requires the agent_id to be
# listed here and raises if it's missing, rather than silently falling back
# to a stale per-file default). To swap a model, edit this file only.
#
# Listed in pipeline execution order (see
# \.claude\plans\i-updated-the-list-wise-pnueli.md — Stages A-D).
# Currently Haiku across the board for test purposes.
#
# TriageAgent is not listed: it's a pure Python threshold gate with no LLM
# call. PatternAgent was removed (dead code — never invoked by the pipeline).

# For testing: "claude-haiku-4-5-20251001",

AGENT_MODELS: dict[str, str] = {
 # --- Stage A: decompose (once) ---
 # Extracts up to 7 Critical/High-impact catalyst/risk sub-questions (each
 # resolvable within 12 months) from the position's thesis and risk
 # profile. Does not classify long/short — stance is an aggregation output.
 "question_definition": "claude-opus-4-8",

 # --- Stage B: shared symbol-level evidence (once) ---
 # Macro analyst: builds a decision tree from VIX, DXY, rates, and sector
 # ETF signals; shared context for every sub-question.
 "macroq": "claude-haiku-4-5-20251001",

 # Symbol-level downside-floor backstop: base-rate risk floor, plus a
 # scale-aware judgment of whether the sub-question density found in
 # decomposition is unusual for a company of this size.
 "risk_judge": "claude-sonnet-5",

 # Financial evidence specialist: earnings trajectory, FCF quality,
 # beat/miss trend. Primary evidence for sub-questions tagged
 # evidence_source=earnings. [parallel with primary_source]
 "earnings": "claude-sonnet-5",

 # Primary-source evidence specialist: filings, transcripts, guidance.
 # Primary evidence for sub-questions tagged evidence_source=primary_source.
 # [parallel with earnings]
 "primary_source": "claude-sonnet-5",

 # Technical analyst: RSI/MACD momentum regime. [parallel with trend, volume]
 "momentum": "claude-haiku-4-5-20251001",

 # Technical analyst: moving-average alignment and ADX trend regime.
 # [parallel with momentum, volume]
 "trend": "claude-haiku-4-5-20251001",

 # Technical analyst: whether volume confirms or diverges from trend.
 # [parallel with momentum, trend]
 "volume": "claude-haiku-4-5-20251001",

 # Technical judge: synthesizes momentum/trend/volume into one verdict.
 # Primary evidence for sub-questions tagged evidence_source=technical.
 "tech_judge": "claude-haiku-4-5-20251001",

 # --- Stage C: per-sub-question forecast (N <= 7, fanned out in parallel) ---
 # Superforecaster: forecasts ONE sub-question via inside view, outside
 # view, pre-mortem, reference class. Runs once per surviving sub-question.
 "elicitation": "claude-opus-4-8",

 # Bias reviewer: devil's-advocate critique of one sub-question's
 # elicitation, scoped to that question only — never the whole thesis.
 "review": "claude-sonnet-5",

 # Probability calibrator: shrinkage, confidence interval, and rationale
 # for one sub-question's final calibrated probability.
 "confidence_judge": "claude-haiku-4-5-20251001",

 # --- Stage D: aggregate (once) ---
 # Final decision agent: grades each sub-question's rationale quality,
 # proposes a bounded (+/-0.30) adjustment to the code-computed mechanical
 # expected-value score, and issues the buy/sell/hold/pass recommendation.
 "aggregation": "claude-opus-4-8",
}
