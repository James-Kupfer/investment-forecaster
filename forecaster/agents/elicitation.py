import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class ElicitationAgent(BaseAgent):
    agent_id = "elicitation"
    model = "claude-sonnet-4-6"

    def run(
        self,
        symbol: str,
        question: str,
        all_context: dict,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Forecasting question: {question}\n\n"
                    f"Prior agent outputs:\n{json.dumps(all_context, indent=2)}\n\n"
                    "Apply inside view, outside view, pre-mortem, and reference class forecasting. "
                    "Output: initial_probability (0-1), confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=3072)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            invq3_p=result.output.get("final_probability") or result.output.get("initial_probability"),
            invq3_confidence=result.output.get("confidence"),
            invq3_rationale=result.output.get("rationale"),
            invq3_model=self.model,
            invq3_prompt_version=result.prompt_version_id,
            elicitation_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
