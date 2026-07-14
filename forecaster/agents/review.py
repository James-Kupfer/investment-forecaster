import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_question_columns
from forecaster.utils import extract_json


class ReviewAgent(BaseAgent):
    """Reviews a single sub-question's elicitation output for bias — devil's
    advocate scoped to one question, not the whole position (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md)."""

    agent_id = "review"

    def run(
        self,
        question: dict,
        elicitation_output: dict,
        symbol_context: dict,
        question_id: int,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Sub-question: {json.dumps(question)}\n\n"
                    f"Elicitation output: {json.dumps(elicitation_output)}\n\n"
                    f"Full symbol context:\n{json.dumps(symbol_context, indent=2)}\n\n"
                    "Review for logical errors, overconfidence, anchoring, circular reasoning, "
                    "or missing evidence — specific to THIS sub-question, not the position as "
                    "a whole. Output: review_flag (true if revision needed), critique, "
                    "revised_probability (0-1 or null), confidence (high/medium/low), rationale."
                ),
            }
        ]
        # Now on Sonnet, whose reasoning draws from this same max_tokens pool
        # (no separate thinking budget) -- observed up to ~6.3k (78% of the old
        # 8096 cap, the tightest margin of any agent short of an actual failure)
        # on a real run, sized well above that for comfortable headroom.
        result = self.call(messages, system=system_prompt, max_tokens=16000)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        flag = result.output.get("review_flag")
        review_flag = flag if isinstance(flag, bool) else None
        update_forecast_question_columns(
            question_id,
            review_flag=review_flag,
            review_rationale=result.output.get("critique") or result.output.get("rationale"),
            question_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
