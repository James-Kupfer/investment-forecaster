import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class TrendAgent(BaseAgent):
    agent_id = "trend"
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
                    f"MA alignment: {tech_context.get('ma_alignment', 'N/A')}\n"
                    f"ADX: {tech_context.get('adx', 'N/A')}\n\n"
                    "Assess the trend regime. Output: trend_signal (uptrend/downtrend/sideways), "
                    "confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=512)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            trend_signal=result.output.get("trend_signal"),
            trend_ma_alignment=(tech_context.get("ma_alignment") or "")[:200],
            trend_confidence=result.output.get("confidence"),
            trend_rationale=result.output.get("rationale"),
            trend_model=self.model,
            trend_prompt_version=result.prompt_version_id,
            trend_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
