import json
import logging
from datetime import date, timedelta
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json

logger = logging.getLogger(__name__)


class QuestionDefinitionAgent(BaseAgent):
    """Decomposes a position's thesis + risks into scorable Critical/High-impact
    sub-questions (catalysts and risks), each independently forecastable through
    the elicitation->review->confidence chain. Does not classify long/short —
    stance is an aggregation output, not a decomposition input (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md)."""

    agent_id = "question_definition"

    MAX_QUESTIONS = 20

    _HIGH_OR_ABOVE = {"critical", "high"}

    @classmethod
    def enforce_admission_gate(cls, output: dict) -> dict:
        """Deterministically re-enforce the step-3 admission gate in code —
        defense-in-depth against the LLM scoring a candidate that fails its
        own gate. Observed live on CEF: the model's step-11 self-audit
        correctly identified a risk as Impact-Medium/Likelihood-Medium
        ("this does NOT clear the step-3b gate") and then scored it anyway
        ("retained decision below") -- a single LLM pass can articulate a
        rule violation and still not act on it, the same failure mode
        CLAUDE.md already documents for the mechanical aggregation score.
        Never trust prose self-policing for a mechanically checkable rule;
        check it here instead.

        A catalyst is admitted iff impact_magnitude is critical/high (the
        severity gate, step 3a). A risk is admitted iff impact_magnitude is
        critical/high OR risk_likelihood is "high" (the broadened Impact-High
        OR Likelihood-High gate, step 3b) -- risk_likelihood is a dedicated
        field precisely because impact_magnitude alone (the risk's Impact
        component) can't distinguish a legitimate Likelihood-High admission
        from a Medium/Medium candidate that never should have been scored.
        A risk missing risk_likelihood is treated as failing it (fail safe,
        not fail open) rather than trusting an unverifiable claim."""
        output = dict(output)
        questions = output.get("questions") or []
        monitor_list = list(output.get("monitor_list") or [])
        nearterm_count = output.get("nearterm_critical_high_count")

        kept, demoted = [], []
        for q in questions:
            magnitude = (q.get("impact_magnitude") or "").lower()
            if magnitude in cls._HIGH_OR_ABOVE:
                kept.append(q)
                continue
            if q.get("type") == "risk" and (q.get("risk_likelihood") or "").lower() == "high":
                kept.append(q)
                continue
            demoted.append(q)

        if demoted:
            logger.warning(
                "QuestionDefinitionAgent: %d question(s) failed the deterministic "
                "admission gate despite being scored by the model -- demoting to "
                "monitor_list: %s",
                len(demoted), [q.get("question_text") for q in demoted],
            )
            for q in demoted:
                monitor_list.append({
                    "description": q.get("question_text") or q.get("rationale") or "(unlabeled)",
                    "reason_excluded": "impact_below_high",
                })
            if isinstance(nearterm_count, int):
                # nearterm_critical_high_count is meant to include gate-passing
                # candidates pushed to monitor_list by the 20-cap, so it can
                # legitimately exceed len(questions) -- but we can't assume
                # the model's count actually included these demoted (gate-
                # FAILING, not cap-overflowed) candidates; live-observed on
                # CEF it did not, and blindly subtracting produced 0 instead
                # of the correct 2. Preserve the model's claimed cap-overflow
                # buffer (whatever it counted beyond its own scored set)
                # against the verified `kept` count instead of trusting its
                # arithmetic against a set that included gate violations.
                buffer = max(0, nearterm_count - len(questions))
                nearterm_count = len(kept) + buffer

        output["questions"] = kept
        output["monitor_list"] = monitor_list
        output["nearterm_critical_high_count"] = nearterm_count
        return output

    @classmethod
    def cap_questions(cls, output: dict) -> dict:
        """Enforce the MAX_QUESTIONS cap in code as defense-in-depth — the
        prompt already instructs a 20-question cap, but LLMs don't always
        perfectly follow numeric constraints. Excess questions are simply
        truncated here (the prompt is responsible for putting the most
        impactful ones first; any it drops should already be in
        monitor_list, not silently lost)."""
        output = dict(output)
        output["questions"] = (output.get("questions") or [])[: cls.MAX_QUESTIONS]
        return output

    def run(
        self,
        symbol: str,
        position: dict,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        today = date.today().isoformat()
        cutoff_date = (date.today() + timedelta(days=365)).isoformat()

        fields = [
            (
                "Instrument type (per portfolio tracker; may be stale/coarse -- "
                "trust the Business section's own classification if they conflict)",
                position.get("instrument_type"),
            ),
            ("Investment thesis", position.get("thesis")),
            ("Risks (Likelihood/Impact)", position.get("risks")),
            ("Business", position.get("business")),
            ("Competitive landscape", position.get("competitive_landscape")),
            ("Financials", position.get("financials")),
            ("Hold period", position.get("hold_period")),
            ("Hold period rationale", position.get("hold_period_rationale")),
            ("Profile confidence", position.get("profile_confidence")),
            ("Profile rationale", position.get("profile_rationale")),
        ]
        field_text = "\n".join(
            f"{label}: {value}" for label, value in fields if value not in (None, "")
        )

        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Today's date: {today}\n"
                    f"12-month decomposition cutoff: {cutoff_date}\n\n"
                    f"{field_text}\n\n"
                    "Decompose this position's thesis and risks into scorable sub-questions."
                ),
            }
        ]
        # Extended thinking (used by claude-sonnet-5/claude-opus-5) counts
        # against max_tokens with no separate thinking budget, so this needs
        # more headroom than a non-thinking model would -- set generously above
        # any observed usage (this agent is now on Opus).
        result = self.call(messages, system=system_prompt, max_tokens=24000)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)

        result.output = self.enforce_admission_gate(result.output)
        result.output = self.cap_questions(result.output)

        update_forecast_columns(
            forecast_id,
            monitor_list=json.dumps(result.output.get("monitor_list") or []),
            nearterm_critical_high_count=result.output.get("nearterm_critical_high_count"),
            question_def_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
