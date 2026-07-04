from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class EarningsAgent(BaseAgent):
    agent_id = "earnings"
    model = "claude-haiku-4-5-20251001"

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
                    "Assess the earnings trajectory and FCF generation. "
                    "Output: signal (bullish/bearish/neutral), confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=1536)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        signal = result.output.get("signal") or result.output.get("earnings_trend")
        rationale = result.output.get("rationale") or result.output.get("fcf_assessment") or ""
        update_forecast_columns(
            forecast_id,
            earnings_signal=(signal or "")[:200],
            earnings_confidence=result.output.get("confidence"),
            earnings_rationale=rationale,
            earnings_model=self.model,
            earnings_prompt_version=result.prompt_version_id,
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
