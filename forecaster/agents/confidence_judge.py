import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_question_columns
from forecaster.utils import extract_json


class ConfidenceJudgeAgent(BaseAgent):
    """Applies shrinkage rules to calibrate a single sub-question's final
    probability (see C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md).
    Position sizing is now decided at aggregation across all of a position's
    sub-questions, not per question — sizing_haircut/calibration_notes here feed
    that step but are not themselves a sizing decision."""

    agent_id = "confidence_judge"

    def run(
        self,
        elicitation_output: dict,
        review_output: dict,
        question_id: int,
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
                    "Produce a final calibrated probability with confidence interval for this "
                    "sub-question. Output: final_probability (0-1), sizing_haircut (0-1), "
                    "confidence (high/medium/low), calibration_notes."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=8000)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_question_columns(
            question_id,
            final_probability=result.output.get("final_probability"),
            confidence=result.output.get("confidence"),
            model_id=self.model,
            forecast_rationale=result.output.get("calibration_notes") or result.output.get("rationale"),
            question_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
