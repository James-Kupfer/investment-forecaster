import json
from datetime import date, timedelta
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class QuestionDefinitionAgent(BaseAgent):
    """Decomposes a position's thesis + risks into scorable Critical/High-impact
    sub-questions (catalysts and risks), each independently forecastable through
    the elicitation->review->confidence chain. Does not classify long/short —
    stance is an aggregation output, not a decomposition input (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md)."""

    agent_id = "question_definition"

    MAX_QUESTIONS = 7

    @classmethod
    def cap_questions(cls, output: dict) -> dict:
        """Enforce the MAX_QUESTIONS cap in code as defense-in-depth — the
        prompt already instructs a 7-question cap, but LLMs don't always
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
            ("Instrument type", position.get("instrument_type")),
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
        # Extended thinking (used by claude-sonnet-5/claude-opus-4-8) counts
        # against max_tokens with no separate thinking budget, so this needs
        # more headroom than a non-thinking model would -- set generously above
        # any observed usage (this agent is now on Opus).
        result = self.call(messages, system=system_prompt, max_tokens=24000)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)

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
