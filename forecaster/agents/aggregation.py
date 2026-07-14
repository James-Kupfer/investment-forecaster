import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns, update_forecast_question_columns
from forecaster.utils import extract_json

_SEVERITY_WEIGHT = {"critical": 4, "high": 3}

# Bounded adjustment: the LLM may not move the mechanical score by more than this
# in either direction — decision 2 in the plan: "bounded", never silently
# replacing the mechanical backbone.
_MAX_ADJUSTMENT = 0.30

_BUY_THRESHOLD = 0.35
_SELL_THRESHOLD = -0.35

# Risk/reward asymmetry: a position that can move 10x in a year justifies accepting
# more mechanical-score risk than one with a capped/linear payoff at the same
# probability profile (Kelly-style — probability x magnitude, not just probability x
# qualitative severity tier, which is all compute_mechanical_score's fixed
# critical/high weights capture on their own). Both thresholds move toward more risk
# tolerance together: buy gets easier to trigger, sell gets harder (don't dump a
# moonshot candidate on a single bad data point) — both by the same amount, since
# the underlying justification (large asymmetric payoff) applies symmetrically.
#
# asymmetric_rating is the investment-profile skill's own categorical field
# (positions.asymmetric_rating): High/Medium/Low/No, rating the plausible ~1-year
# return path as High=10x, Medium>=5x, Low>=1x, else No. The adjustment is derived
# directly from those floor multiples, scaled against "High" (10x) as the fully
# asymmetric reference — not an independently-invented scale.
_MAX_ASYMMETRY_ADJUSTMENT = 0.20
_ASYMMETRY_RATING_MULTIPLES = {"high": 10.0, "medium": 5.0, "low": 1.0, "no": 0.0}
_ASYMMETRY_REFERENCE_MULTIPLE = 10.0

# compute_mechanical_score's normalization pins the score to +/-1 whenever every
# scored question lands on the same side of the ledger (guaranteed at n=1, likely
# at n=2-3) — the probability of that lone question never enters the sign or
# magnitude, only which side it's on. The signal is still real (decision 2 never
# discards a scored question), but the buy/sell thresholds widen — more risk
# tolerance toward "hold" — the fewer questions back the score, tapering linearly
# to zero once a position has _FULL_QUESTION_COUNT or more (a fuller decomposition
# no longer risks being dominated by a single item).
_MAX_LOW_N_ADJUSTMENT = 0.20
_FULL_QUESTION_COUNT = 4


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
        behind the score, for compute_low_n_adjustment."""
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
    def compute_low_n_adjustment(scored_count: int) -> float:
        """
        Points to widen both buy/sell thresholds toward "hold" as scored_count
        drops below _FULL_QUESTION_COUNT — a lone scored question (or a
        thin 2-3 question set) gets fully floored/ceilinged to +/-1 by
        compute_mechanical_score regardless of its actual probability, so a
        thinner set should need a stronger adjusted_score to still clear the
        buy/sell bar. Zero once scored_count >= _FULL_QUESTION_COUNT (a fuller
        decomposition is no longer at risk of one item dominating the score).
        Zero for scored_count <= 0 too — derive_recommendation already sends
        an empty scored set to "pass", not a floored buy/sell.
        """
        if scored_count <= 0 or scored_count >= _FULL_QUESTION_COUNT:
            return 0.0
        scale = (_FULL_QUESTION_COUNT - scored_count) / (_FULL_QUESTION_COUNT - 1)
        return round(scale * _MAX_LOW_N_ADJUSTMENT, 4)

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
        adjusted_score: float,
        llm_recommendation,
        buy_threshold: float = _BUY_THRESHOLD,
        sell_threshold: float = _SELL_THRESHOLD,
    ) -> str:
        """buy/sell/hold/pass per decision 4: pass means insufficient scorable
        signal (empty question set), distinct from hold (signal exists, nets
        neutral). Falls back to threshold mapping if the LLM's own
        recommendation is missing or malformed. buy_threshold/sell_threshold
        default to the base constants but may be shifted by
        compute_asymmetry_adjustment for a position with convex upside."""
        if not questions:
            return "pass"
        if llm_recommendation in ("buy", "sell", "hold", "pass"):
            return llm_recommendation
        if adjusted_score >= buy_threshold:
            return "buy"
        if adjusted_score <= sell_threshold:
            return "sell"
        return "hold"

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
        asymmetry_adjustment = self.compute_asymmetry_adjustment(asymmetric_rating)
        low_n_adjustment = self.compute_low_n_adjustment(scored_count)
        buy_threshold = _BUY_THRESHOLD - asymmetry_adjustment + low_n_adjustment
        sell_threshold = _SELL_THRESHOLD - asymmetry_adjustment - low_n_adjustment

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
                    f"Scored question count: {scored_count} (of {_FULL_QUESTION_COUNT} treated as a "
                    f"full decomposition). With few scored questions, the mechanical score is "
                    f"normalized against a thin or single-item ledger and gets pinned toward the "
                    f"+/-1 floor/ceiling regardless of that question's actual probability — the "
                    f"signal is still real, it is just less diversified. The thresholds above "
                    f"already include a low-n widening of {low_n_adjustment:+.4f} toward hold for "
                    f"this reason (zero once scored_count >= {_FULL_QUESTION_COUNT}); do not "
                    f"re-litigate that widening itself, only the recommendation given it.\n\n"
                    "For EACH sub-question, grade the quality and logic of its forecast rationale "
                    "(0-1) — is it sound, evidence-backed, non-circular? Note any concerns. "
                    "Then propose a bounded adjustment (no more than +/-0.30) to the mechanical "
                    "score, with a specific rationale citing which questions were down-weighted "
                    "for weak reasoning and why, and how the risk judge's floor/density flag "
                    "factors in. Finally, recommend buy, sell, hold, or pass, with a full "
                    "decision rationale. Output: question_grades (list of {question_index, "
                    "rationale_quality_score, rationale_quality_notes}), adjustment_delta "
                    "(-0.30 to 0.30), score_adjustment_rationale, recommendation "
                    "(buy|sell|hold|pass), decision_rationale, confidence (high/medium/low)."
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
        result = self.call(messages, system=system_prompt, max_tokens=32000)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)

        delta = self.clamp_adjustment(result.output.get("adjustment_delta"))
        adjusted_score = max(-1.0, min(1.0, mechanical_score + delta))
        recommendation = self.derive_recommendation(
            questions, adjusted_score, result.output.get("recommendation"),
            buy_threshold=buy_threshold, sell_threshold=sell_threshold,
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
            score_adjustment_rationale=result.output.get("score_adjustment_rationale"),
            decision_rationale=result.output.get("decision_rationale"),
            expected_upside_impact=upside_impact,
            expected_downside_impact=downside_impact,
            upside_downside_ratio=upside_downside_ratio,
            asymmetry_adjustment=asymmetry_adjustment,
            low_n_adjustment=low_n_adjustment,
            question_count=scored_count,
            buy_threshold_used=buy_threshold,
            sell_threshold_used=sell_threshold,
            monitor_list=json.dumps(monitor_list),
            recommendation=recommendation,
            aggregation_output=json.dumps(result.output),
            schema_version=2,
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
