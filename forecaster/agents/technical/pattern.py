import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class PatternAgent(BaseAgent):
    agent_id = "pattern"
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
                    f"RSI: {tech_context.get('rsi', 'N/A')}\n"
                    f"Volume: {tech_context.get('volume', 'N/A')}\n\n"
                    "Identify chart patterns and key price levels. "
                    "Output: patterns (list of name/signal/reliability), key_level (price float or null), "
                    "confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=512)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        patterns = result.output.get("patterns") or []
        dominant = patterns[0] if patterns else {}
        rationale = result.output.get("rationale") or json.dumps(patterns)
        update_forecast_columns(
            forecast_id,
            pattern_signal=dominant.get("signal"),
            pattern_key_level=result.output.get("key_level"),
            pattern_confidence=dominant.get("reliability") or result.output.get("confidence"),
            pattern_rationale=rationale,
            pattern_model=self.model,
            pattern_prompt_version=result.prompt_version_id,
            pattern_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
