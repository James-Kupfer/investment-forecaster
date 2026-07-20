import json
import logging
import math
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns, update_forecast_question_columns
from forecaster.utils import normalize_confidence_word

logger = logging.getLogger(__name__)

_SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}

_VALID_RECOMMENDATIONS = ("Buy", "Sell", "Hold", "Pass")

_VALID_CONFIDENCES = ("High", "Medium", "Low")

# Constrains the model at decode time to exactly this shape. This is the whole
# reason the agent can parse strictly instead of salvaging: it is structurally
# impossible for the model to fragment its answer across several JSON objects,
# narrate around it in prose, omit a required field, or invent a recommendation
# outside the enum. Observed live on forecast 30 (Haiku, prompt v2.4): the model
# closed a partial object early, wrote "**Recommendation: HOLD**" as markdown,
# then appended two more single-key objects — extract_json kept the first (most
# keys) and silently discarded decision_rationale, confidence, AND the
# recommendation, which had never been JSON at all.
#
# Note what is deliberately NOT expressed here: adjustment_delta's [-0.30, 0.30]
# bound. Structured outputs do not support numeric constraints (minimum/maximum),
# and that bound is already enforced deterministically by clamp_adjustment — the
# right place for it, since a malformed value must become 0.0 rather than error.
# additionalProperties/required are mandatory on every object in the schema.
AGGREGATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "question_grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_index": {"type": "integer"},
                    "rationale_quality_score": {"type": "number"},
                    "rationale_quality_notes": {"type": "string"},
                },
                "required": [
                    "question_index",
                    "rationale_quality_score",
                    "rationale_quality_notes",
                ],
                "additionalProperties": False,
            },
        },
        "adjustment_delta": {"type": "number"},
        "score_adjustment_rationale": {"type": "string"},
        "recommendation": {"type": "string", "enum": list(_VALID_RECOMMENDATIONS)},
        "decision_rationale": {"type": "string"},
        "confidence": {"type": "string", "enum": list(_VALID_CONFIDENCES)},
    },
    "required": [
        "question_grades",
        "adjustment_delta",
        "score_adjustment_rationale",
        "recommendation",
        "decision_rationale",
        "confidence",
    ],
    "additionalProperties": False,
}

# Bounded adjustment: the LLM may not move the mechanical score by more than this
# in either direction — decision 2 in the plan: "bounded", never silently
# replacing the mechanical backbone.
_MAX_ADJUSTMENT = 0.30

_BUY_THRESHOLD = 0.35
_SELL_THRESHOLD = -0.35

# Risk/reward asymmetry: a position with a plausible multibagger payoff justifies
# accepting more mechanical-score risk than one with a capped/linear payoff at the
# same probability profile. Both thresholds move toward more risk tolerance together:
# buy gets easier to trigger, sell gets harder (don't dump a moonshot on a single bad
# data point) — both by the same amount.
#
# asymmetric_rating is the investment-profile skill's own categorical field
# (positions.asymmetric_rating): High/Medium/Low/No, rating the plausible ~1-year
# return path as an Nx return — High=5x (+500%), Medium=2x (+200%), Low=1x (a double,
# +100%), else No (short of a double). Upside-only: "No" is the residual and gets zero
# shift, never a downside penalty. The adjustment is proportional to the rating's
# return multiple, scaled against High (5x) as the fully asymmetric reference.
_MAX_ASYMMETRY_ADJUSTMENT = 0.25
_ASYMMETRY_RATING_MULTIPLES = {"high": 5.0, "medium": 2.0, "low": 1.0, "no": 0.0}
_ASYMMETRY_REFERENCE_MULTIPLE = 5.0

# Conviction multiplier: compute_mechanical_score's normalization ((up-down)/(up+down))
# preserves only direction and one-sidedness — never how much total weighted evidence
# is actually on the table, so a lone low-probability question pins the score to +/-1.
# We restore magnitude by scaling the normalized tilt by a saturating conviction factor
# in [0,1): conviction = 1 - exp(-M/k), where M = upside_impact + downside_impact (total
# weighted evidence). A thin, low-M ledger attenuates the decision score toward hold; a
# well-covered one keeps near-full tilt. This replaces the old low-n threshold widening
# (a thin ledger now attenuates the score directly rather than widening the bar). k is a
# saturation scale to be calibrated once position-level outcomes exist.
#
# Below M_FLOOR there is too little total evidence to act at all: the position is Pass
# (insufficient signal) regardless of how one-sided the tilt is — distinct from Hold
# (real signal that nets neutral). Both k and M_FLOOR are priors pending calibration.
_K_CONVICTION = 7.0
_M_FLOOR = 1.0


class AggregationAgent(BaseAgent):
    """Aggregates all of a position's decomposed sub-question forecasts into a
    buy/sell/hold/pass recommendation. The mechanical expected-value score is
    always computed deterministically in code (the auditable backbone); the
    LLM's role is bounded to (a) grading each sub-question's rationale quality
    and (b) proposing a capped, logged adjustment — it never silently replaces
    the mechanical score (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md, decisions 2 and 8)."""

    agent_id = "aggregation"

    @staticmethod
    def compute_mechanical_score(questions: list) -> tuple:
        """Deterministic expected-value backbone (decision 2 in the plan) —
        never LLM-computed. Returns (mechanical_score, upside_impact,
        downside_impact, upside_downside_ratio, scored_count). mechanical_score
        is normalized to [-1, +1] so positions are comparable regardless of how
        many sub-questions they have. scored_count is the number of questions
        that actually contributed a weighted probability (excludes ones with no
        final_probability or a zero severity weight) — the true sample size
        behind the score."""
        upside_impact = 0.0
        downside_impact = 0.0
        scored_count = 0
        for q in questions:
            p = q.get("final_probability")
            weight = _SEVERITY_WEIGHT.get(q.get("impact_magnitude"), 0)
            if p is None or not weight:
                continue
            scored_count += 1
            contribution = float(p) * weight
            if q.get("impact_direction") == "+":
                upside_impact += contribution
            else:
                downside_impact += contribution

        total = upside_impact + downside_impact
        mechanical_score = (upside_impact - downside_impact) / total if total > 0 else 0.0
        upside_downside_ratio = (upside_impact / downside_impact) if downside_impact > 0 else None
        return mechanical_score, upside_impact, downside_impact, upside_downside_ratio, scored_count

    @staticmethod
    def compute_asymmetry_adjustment(asymmetric_rating) -> float:
        """
        Points to shift both buy/sell thresholds toward more risk tolerance, derived
        from the position's asymmetric_rating (High/Medium/Low/No, from the
        investment-profile skill — see module comment for the multiples). Returns
        0.0 for "No", missing, or an unrecognized value — never guesses a magnitude.
        """
        if not asymmetric_rating:
            return 0.0
        multiple = _ASYMMETRY_RATING_MULTIPLES.get(str(asymmetric_rating).strip().lower())
        if not multiple:
            return 0.0
        scale = min(multiple / _ASYMMETRY_REFERENCE_MULTIPLE, 1.0)
        return round(scale * _MAX_ASYMMETRY_ADJUSTMENT, 4)

    @staticmethod
    def compute_conviction(total_evidence: float) -> float:
        """Saturating conviction multiplier in [0, 1): 1 - exp(-M/_K_CONVICTION),
        where M = total weighted evidence (upside_impact + downside_impact). The
        normalized tilt is scaled by this so a thin, low-evidence ledger attenuates
        the decision score toward hold while a well-covered one keeps near-full tilt.
        Replaces compute_low_n_adjustment (a thin ledger now shrinks the score
        directly instead of widening the threshold). Returns 0.0 for non-positive
        evidence."""
        if total_evidence <= 0:
            return 0.0
        return round(1.0 - math.exp(-total_evidence / _K_CONVICTION), 4)

    @staticmethod
    def clamp_adjustment(delta) -> float:
        """Bound the LLM's proposed adjustment to +/-_MAX_ADJUSTMENT — the
        'bounded' half of decision 2. Never lets a malformed or extreme LLM
        value move the mechanical score more than this."""
        try:
            delta = float(delta or 0.0)
        except (TypeError, ValueError):
            delta = 0.0
        return max(-_MAX_ADJUSTMENT, min(_MAX_ADJUSTMENT, delta))

    @staticmethod
    def derive_recommendation(
        questions: list,
        final_score: float,
        llm_recommendation,
        total_evidence: Optional[float] = None,
        buy_threshold: float = _BUY_THRESHOLD,
        sell_threshold: float = _SELL_THRESHOLD,
    ) -> str:
        """buy/sell/hold/pass per decision 4: Pass means insufficient scorable
        signal, distinct from Hold (signal exists, nets neutral). Two Pass paths:
        an empty question set, and — when total_evidence is supplied — a position
        whose total weighted evidence is below _M_FLOOR (too little to act on,
        regardless of tilt); this floor overrides even a valid LLM recommendation.
        Otherwise returns the LLM's own recommendation when valid, falling back to
        a threshold mapping on final_score (the conviction-scaled tilt).
        buy_threshold/sell_threshold default to the base constants but may be
        shifted by compute_asymmetry_adjustment for a position with convex upside."""
        if not questions:
            return "Pass"
        if total_evidence is not None and total_evidence < _M_FLOOR:
            return "Pass"
        if llm_recommendation in _VALID_RECOMMENDATIONS:
            return llm_recommendation
        if final_score >= buy_threshold:
            return "Buy"
        if final_score <= sell_threshold:
            return "Sell"
        return "Hold"

    def run(
        self,
        questions: list,
        monitor_list: list,
        risk_floor_output: dict,
        forecast_id: int,
        asymmetric_rating: Optional[str] = None,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        mechanical_score, upside_impact, downside_impact, upside_downside_ratio, scored_count = (
            self.compute_mechanical_score(questions)
        )
        total_evidence = round(upside_impact + downside_impact, 4)
        conviction = self.compute_conviction(upside_impact + downside_impact)
        asymmetry_adjustment = self.compute_asymmetry_adjustment(asymmetric_rating)
        buy_threshold = _BUY_THRESHOLD - asymmetry_adjustment
        sell_threshold = _SELL_THRESHOLD - asymmetry_adjustment

        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Sub-questions (each with its full forecast chain output; question_index "
                    f"is its position in this list):\n{json.dumps(questions, indent=2)}\n\n"
                    f"Monitor list (excluded from scoring): {json.dumps(monitor_list, indent=2)}\n\n"
                    f"Risk judge output (symbol-level backstop, scale-adjusted density flag): "
                    f"{json.dumps(risk_floor_output, indent=2)}\n\n"
                    f"Mechanical score (computed deterministically, -1 to +1): {mechanical_score:.4f}\n"
                    f"Expected upside impact: {upside_impact:.4f}\n"
                    f"Expected downside impact: {downside_impact:.4f}\n\n"
                    f"Position risk/reward asymmetry: asymmetric_rating={asymmetric_rating!r} "
                    f"(High=10x, Medium>=5x, Low>=1x, No=none plausible in ~1 year, per the "
                    f"investment-profile skill). This position's buy/sell thresholds have been "
                    f"mechanically shifted by "
                    f"{asymmetry_adjustment:+.4f} toward more risk tolerance (buy_threshold="
                    f"{buy_threshold:.4f}, sell_threshold={sell_threshold:.4f}, vs. the base "
                    f"+/-{_BUY_THRESHOLD:.2f}) — a large asymmetric upside justifies accepting "
                    f"more mechanical-score risk than a capped/linear payoff would. Reflect this "
                    f"explicitly in decision_rationale when it affects your recommendation; do "
                    f"not re-litigate the shift itself, only the recommendation given it.\n\n"
                    f"Total weighted evidence on this position (M = expected upside + downside "
                    f"impact): {total_evidence:.4f}. Conviction multiplier (saturating, "
                    f"1 - exp(-M/{_K_CONVICTION:.0f}), in [0,1)): {conviction:.4f}. The mechanical "
                    f"score is normalized ((up-down)/(up+down)), so it captures direction and "
                    f"one-sidedness but not magnitude — a thin ledger pins it to +/-1. The decision "
                    f"score restores magnitude by scaling the tilt by conviction: final_score = "
                    f"(mechanical_score + your adjustment_delta) x {conviction:.4f}. Judge Buy/Sell/"
                    f"Hold against final_score versus the buy/sell thresholds above, NOT the raw "
                    f"mechanical_score. If M is below {_M_FLOOR:.1f} the position has insufficient "
                    f"total evidence to act and MUST be Pass regardless of tilt (also enforced in "
                    f"code).\n\n"
                    "For EACH sub-question, grade the quality and logic of its forecast rationale "
                    "(0-1) — is it sound, evidence-backed, non-circular? Note any concerns. "
                    "Then propose a bounded adjustment (no more than +/-0.30) to the mechanical "
                    "score, with a specific rationale citing which questions were down-weighted "
                    "for weak reasoning and why, and how the risk judge's floor/density flag "
                    "factors in. Finally, recommend Buy, Sell, Hold, or Pass, with a full "
                    "decision rationale. Output: question_grades (list of {question_index, "
                    "rationale_quality_score, rationale_quality_notes}), adjustment_delta "
                    "(-0.30 to 0.30), score_adjustment_rationale, recommendation "
                    "(Buy|Sell|Hold|Pass), decision_rationale, confidence (High/Medium/Low)."
                ),
            }
        ]
        # 8096 was found (live LIN run) to truncate mid-decision_rationale for a
        # full 7-question set: thorough per-question grading notes (decision 8)
        # times up to 7 questions, plus score_adjustment_rationale and
        # decision_rationale, routinely exceeds it. Truncated JSON silently loses
        # whatever fields come after the cutoff (recommendation has a mechanical
        # fallback via derive_recommendation; decision_rationale does not). This
        # agent is now on Opus, which was separately observed (same live run) to
        # sometimes draft a JSON object, self-correct with narrative text, then
        # emit a second complete object -- effectively doubling total output for
        # a single call. Sized well above that worst case for a full 7-question set.
        result = self.call(
            messages,
            system=system_prompt,
            max_tokens=32000,
            output_config={"format": {"type": "json_schema", "schema": AGGREGATION_SCHEMA}},
        )
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)

        delta = self.clamp_adjustment(result.output.get("adjustment_delta"))
        adjusted_score = max(-1.0, min(1.0, mechanical_score + delta))
        final_score = round(adjusted_score * conviction, 4)

        llm_recommendation = result.output.get("recommendation")
        if questions and (result.error or llm_recommendation not in _VALID_RECOMMENDATIONS):
            # Never fabricate a recommendation the model did not make. This path
            # used to fall through to derive_recommendation's mechanical
            # threshold mapping, which stored the fabricated call as though the
            # model had issued it: on forecast 30 (FNV) that wrote recommendation
            # ='buy' off a 0.357-vs-0.350 margin while the model's own — lost —
            # answer was HOLD, explicitly reasoning that the margin was "within
            # measurement error" and "does not justify a conviction buy". Nothing
            # in the row flagged it. A NULL recommendation already means
            # "not determined" in this schema (that's how _insert_partial_forecast
            # leaves it), so leaving it NULL is honest and needs no new column;
            # the mechanical columns below are still written because they are
            # computed in code and remain valid regardless of the LLM's failure.
            # With AGGREGATION_SCHEMA enforced this should be unreachable — it is
            # an assertion about the schema, not a fallback for the model.
            logger.error(
                "aggregation produced no usable recommendation for forecast_id=%s "
                "(error=%r, recommendation=%r) — leaving recommendation NULL rather "
                "than substituting a mechanical threshold read. final_score=%.4f "
                "(adjusted_score=%.4f x conviction=%.4f) vs buy_threshold=%.4f/sell_threshold=%.4f.",
                forecast_id, result.error, llm_recommendation,
                final_score, adjusted_score, conviction, buy_threshold, sell_threshold,
            )
            recommendation = None
        else:
            recommendation = self.derive_recommendation(
                questions, final_score, llm_recommendation,
                total_evidence=total_evidence,
                buy_threshold=buy_threshold, sell_threshold=sell_threshold,
            )

        # Same "never fabricate" posture as recommendation above, scoped to
        # confidence -- reuses the same normalize_confidence_word every other
        # confidence-bearing column (macroq_confidence, risk_judge_confidence,
        # forecast_questions.confidence) already goes through, which fails
        # safe to None on an unrecognized value rather than risking a
        # StringDataRightTruncation crash on the VARCHAR(10) column.
        confidence = None if result.error else normalize_confidence_word(
            result.output.get("confidence"), context=f"aggregation/forecast_{forecast_id}"
        )

        for grade in (result.output.get("question_grades") or []):
            idx = grade.get("question_index")
            if idx is None or not isinstance(idx, int) or not (0 <= idx < len(questions)):
                continue
            qid = questions[idx].get("id")
            if qid is None:
                continue
            update_forecast_question_columns(
                qid,
                rationale_quality_score=grade.get("rationale_quality_score"),
                rationale_quality_notes=grade.get("rationale_quality_notes"),
            )

        update_forecast_columns(
            forecast_id,
            mechanical_score=mechanical_score,
            adjusted_score=adjusted_score,
            conviction=conviction,
            total_evidence=total_evidence,
            final_score=final_score,
            score_adjustment_rationale=result.output.get("score_adjustment_rationale"),
            decision_rationale=result.output.get("decision_rationale"),
            expected_upside_impact=upside_impact,
            expected_downside_impact=downside_impact,
            upside_downside_ratio=upside_downside_ratio,
            asymmetry_adjustment=asymmetry_adjustment,
            question_count=scored_count,
            buy_threshold_used=buy_threshold,
            sell_threshold_used=sell_threshold,
            monitor_list=json.dumps(monitor_list),
            recommendation=recommendation,
            confidence=confidence,
            aggregation_output=json.dumps(result.output),
            schema_version=2,
        )
        return result

    def _parse_response(self, response) -> dict:
        """Strict parse, deliberately NOT extract_json. AGGREGATION_SCHEMA
        constrains the decoder, so the response text is a single valid JSON
        object matching it or the call did not succeed — there is no third
        outcome worth salvaging. extract_json's heuristics exist to guess intent
        from a malformed response and return whatever they can; running them here
        would re-introduce exactly the silent partial-recovery this agent is
        moving away from. A parse failure now raises, BaseAgent.call captures it
        into AgentResult.error, and log_call persists it — loud, not silent."""
        text = self.extract_text_block(response) or ""
        return json.loads(text)
