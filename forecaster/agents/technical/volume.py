import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class VolumeAgent(BaseAgent):
    agent_id = "volume"
    model = "claude-haiku-4-5-20251001"

    def run(
        self,
        symbol: str,
        tech_context: dict,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Volume: {tech_context.get('volume', 'N/A')}\n"
                    f"Trend: {tech_context.get('ma_alignment', 'N/A')}\n\n"
                    "Assess whether volume confirms or contradicts the trend. "
                    "Output: volume_signal (confirming/diverging/neutral), "
                    "confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=512)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            volume_signal=result.output.get("volume_signal"),
            volume_confidence=result.output.get("confidence"),
            volume_rationale=result.output.get("rationale"),
            volume_model=self.model,
            volume_prompt_version=result.prompt_version_id,
            volume_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
