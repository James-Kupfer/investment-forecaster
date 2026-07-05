import json
import re
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


def _parse_rsi_value(rsi_desc: str) -> Optional[float]:
    m = re.search(r'RSI ([\d.]+)', rsi_desc)
    return float(m.group(1)) if m else None


class MomentumAgent(BaseAgent):
    agent_id = "momentum"
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
                    f"RSI: {tech_context.get('rsi', 'N/A')}\n"
                    f"MACD: {tech_context.get('macd', 'N/A')}\n\n"
                    "Assess the momentum regime. Output: momentum_signal (bullish/bearish/neutral), "
                    "confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=512)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            momentum_rsi=_parse_rsi_value(tech_context.get("rsi", "")),
            momentum_macd=(tech_context.get("macd") or "")[:50],
            momentum_signal=result.output.get("momentum_signal"),
            momentum_confidence=result.output.get("confidence"),
            momentum_rationale=result.output.get("rationale"),
            momentum_model=self.model,
            momentum_prompt_version=result.prompt_version_id,
            momentum_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
