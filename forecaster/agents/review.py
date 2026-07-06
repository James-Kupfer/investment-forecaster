import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class ReviewAgent(BaseAgent):
    agent_id = "review"
    model = "claude-sonnet-4-6"

    def run(
        self,
        elicitation_output: dict,
        all_context: dict,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Elicitation output: {json.dumps(elicitation_output)}\n\n"
                    f"Full context:\n{json.dumps(all_context, indent=2)}\n\n"
                    "Review for logical errors, overconfidence, anchoring, or missing evidence. "
                    "Output: review_flag (true if revision needed), critique, "
                    "revised_probability (0-1 or null), confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=8096)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        flag = result.output.get("review_flag")
        flag_bit = 1 if flag is True else (0 if flag is False else None)
        update_forecast_columns(
            forecast_id,
            review_flag=flag_bit,
            review_rationale=result.output.get("critique") or result.output.get("rationale"),
            review_confidence=result.output.get("confidence"),
            review_model=self.model,
            review_prompt_version=result.prompt_version_id,
            review_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
