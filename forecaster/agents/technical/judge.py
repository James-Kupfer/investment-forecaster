import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class TechnicalJudgeAgent(BaseAgent):
    agent_id = "tech_judge"
    model = "claude-sonnet-4-6"

    def run(
        self,
        tech_results: list,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        labels = ["momentum", "trend", "volume", "pattern"]
        lines = [
            f"{label}: {json.dumps(r.output)}"
            for label, r in zip(labels, tech_results)
            if r and r.output
        ]
        context = "\n".join(lines) or "No technical signals available."
        messages = [
            {
                "role": "user",
                "content": (
                    f"Technical agent outputs:\n{context}\n\n"
                    "Synthesise into a single verdict. Output: technical_verdict (bullish/bearish/neutral), "
                    "key_level (price float or null), confidence (high/medium/low), rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=1536)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            technical_signal=result.output.get("technical_verdict"),
            technical_key_level=result.output.get("key_level"),
            technical_confidence=result.output.get("confidence"),
            technical_rationale=result.output.get("rationale"),
            technical_judge_model=self.model,
            technical_judge_prompt_version=result.prompt_version_id,
            technical_judge_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
