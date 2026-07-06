import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class RiskJudgeAgent(BaseAgent):
    agent_id = "risk_judge"
    model = "claude-sonnet-4-6"

    def run(
        self,
        symbol: str,
        thesis: str,
        macro_summary: str,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Investment thesis: {thesis}\n"
                    f"Macro environment: {macro_summary}\n\n"
                    "Identify the top risks and provide an invq2_floor (minimum downside probability 0-1)."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=4096)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            risk_judge_output=json.dumps(result.output),
            invq2_floor=result.output.get("invq2_floor"),
            risk_judge_confidence=result.output.get("confidence"),
            risk_judge_rationale=result.output.get("rationale"),
            risk_judge_model=self.model,
            risk_judge_prompt_version=result.prompt_version_id,
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
