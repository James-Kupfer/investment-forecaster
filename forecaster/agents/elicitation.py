import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_question_columns
from forecaster.utils import extract_json


class ElicitationAgent(BaseAgent):
    """Forecasts a single decomposed sub-question (see question_definition), not
    the position's thesis as a whole. symbol_context is the shared Stage-B
    evidence; primary_evidence is whichever specialist output the question's
    evidence_source names, foregrounded as the primary input (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md)."""

    agent_id = "elicitation"

    def run(
        self,
        symbol: str,
        question: dict,
        symbol_context: dict,
        question_id: int,
        forecast_id: int,
        position: Optional[dict] = None,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        primary_evidence = symbol_context.get(question.get("evidence_source"), {})
        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Sub-question: {json.dumps(question)}\n\n"
                    f"Primary evidence ({question.get('evidence_source')}):\n"
                    f"{json.dumps(primary_evidence, indent=2)}\n\n"
                    f"Full symbol context:\n{json.dumps(symbol_context, indent=2)}\n\n"
                    f"Position context: {json.dumps(position or {})}\n\n"
                    "Apply inside view, outside view, pre-mortem, and reference class forecasting "
                    "to THIS specific sub-question — not the position as a whole. "
                    "Output: initial_probability (0-1), confidence (high/medium/low), rationale."
                ),
            }
        ]
        # Now on Sonnet, whose reasoning draws from this same max_tokens pool
        # (no separate thinking budget) -- observed up to ~4.6k on a real run,
        # sized well above that for comfortable headroom.
        result = self.call(messages, system=system_prompt, max_tokens=16000)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_question_columns(
            question_id,
            elicitation_p=result.output.get("final_probability") or result.output.get("initial_probability"),
            question_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
