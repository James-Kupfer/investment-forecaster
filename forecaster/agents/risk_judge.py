import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.utils import extract_json


class RiskJudgeAgent(BaseAgent):
    """Symbol-level downside-floor backstop for the aggregation step. Individual
    risks are now scored as their own sub-questions by the decomposition agent
    (question_definition), so this agent no longer duplicates that per-risk
    scoring — it instead judges whether the *volume* of near-term Critical/High
    questions is unusual for a company of this scale, and escalates the
    downside floor accordingly. A small, single-market company hitting the
    7-question cap is a much stronger risk signal than a diversified
    multinational hitting it (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md, decision 5)."""

    agent_id = "risk_judge"

    def run(
        self,
        symbol: str,
        thesis: str,
        macro_summary: str,
        forecast_id: int,
        drawdown_threshold: Optional[float] = None,
        nearterm_critical_high_count: Optional[int] = None,
        business: Optional[str] = None,
        competitive_landscape: Optional[str] = None,
        financials: Optional[str] = None,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Investment thesis: {thesis}\n"
                    f"Macro environment: {macro_summary}\n"
                    f"Drawdown threshold: {drawdown_threshold if drawdown_threshold is not None else 'not specified'}\n"
                    f"Near-term Critical/High question count (from decomposition, "
                    f"including any pushed to the monitor list by the 7-question cap): "
                    f"{nearterm_critical_high_count if nearterm_critical_high_count is not None else 'not specified'}\n"
                    f"Business: {business or 'not specified'}\n"
                    f"Competitive landscape: {competitive_landscape or 'not specified'}\n"
                    f"Financials: {financials or 'not specified'}\n\n"
                    "Identify the top risks, provide an invq2_floor (minimum downside probability 0-1), "
                    "infer scale/leverage/event-dependence from the available text, and assess whether "
                    "the near-term Critical/High question count is unusual given this position's scale."
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
            scale_adjusted_density_flag=result.output.get("scale_adjusted_density_flag"),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
