import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class PrimarySourceAgent(BaseAgent):
    agent_id = "primary_source"
    model = "claude-sonnet-4-6"

    def run(
        self,
        symbol: str,
        thesis: str,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Investment thesis: {thesis}\n\n"
                    "Identify and weigh primary source evidence for and against the thesis. "
                    "Output: net_assessment (bullish/bearish/neutral), confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=1536)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            primary_signal=(result.output.get("net_assessment") or "")[:200],
            primary_confidence=result.output.get("confidence"),
            primary_rationale=result.output.get("rationale"),
            primary_model=self.model,
            primary_prompt_version=result.prompt_version_id,
            primary_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
