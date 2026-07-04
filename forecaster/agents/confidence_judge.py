import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class ConfidenceJudgeAgent(BaseAgent):
    agent_id = "confidence_judge"
    model = "claude-sonnet-4-6"

    def run(
        self,
        elicitation_output: dict,
        review_output: dict,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Elicitation: {json.dumps(elicitation_output)}\n"
                    f"Review: {json.dumps(review_output)}\n\n"
                    "Produce a final calibrated probability with confidence interval. "
                    "Output: final_probability (0-1), sizing_haircut (0-1, reduction to position size), "
                    "confidence (high/medium/low), calibration_notes."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=1024)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            sizing_haircut=result.output.get("sizing_haircut"),
            confidence_rationale=(result.output.get("calibration_notes") or "")[:1000],
            confidence_confidence=result.output.get("confidence"),
            confidence_judge_model=self.model,
            confidence_prompt_version=result.prompt_version_id,
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
