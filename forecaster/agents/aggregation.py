import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class AggregationAgent(BaseAgent):
    agent_id = "aggregation"
    model = "claude-sonnet-4-6"

    def run(
        self,
        all_outputs: dict,
        forecast_id: int,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"All agent outputs:\n{json.dumps(all_outputs, indent=2)}\n\n"
                    "Produce the final forecast. Output: upside_probability (0-1), "
                    "downside_probability (0-1), compound_conviction (0-1), "
                    "asymmetry_ratio (upside_prob / downside_prob), "
                    "thesis_crux (string), summary (plain-English for investment committee), "
                    "confidence (high/medium/low)."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=1536)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        invq1 = result.output.get("upside_probability")
        invq2 = result.output.get("downside_probability")
        computed_asymmetry = (
            result.output.get("asymmetry_ratio")
            or (round(invq1 / invq2, 4) if invq1 and invq2 and invq2 > 0 else None)
        )
        update_forecast_columns(
            forecast_id,
            invq1_p=invq1,
            invq1_confidence=result.output.get("confidence"),
            invq1_rationale=(result.output.get("summary") or "")[:1000],
            invq1_model=self.model,
            invq1_prompt_version=result.prompt_version_id,
            invq2_p=invq2,
            invq2_confidence=result.output.get("confidence"),
            invq2_rationale=(result.output.get("thesis_crux") or "")[:1000],
            invq2_model=self.model,
            invq2_prompt_version=result.prompt_version_id,
            compound_conviction=result.output.get("compound_conviction"),
            asymmetry_ratio=computed_asymmetry,
        )
        return result

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
