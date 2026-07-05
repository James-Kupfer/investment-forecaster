import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class QuestionDefinitionAgent(BaseAgent):
    agent_id = "question_definition"
    model = "claude-sonnet-4-6"

    def run(
        self,
        symbol: str,
        thesis: str,
        horizon_days: int,
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
                    f"Forecast horizon: {horizon_days} days\n\n"
                    "Formulate a precise, binary forecasting question."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=1024)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            invq3_definition=result.output.get("question"),
            invq3_definition_confidence=result.output.get("confidence"),
            invq3_definition_rationale=result.output.get("rationale"),
            invq3_def_model=self.model,
            invq3_def_prompt_version=result.prompt_version_id,
            question_def_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
