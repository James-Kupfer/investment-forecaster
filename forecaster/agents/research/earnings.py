import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.edgar_client import get_quarterly_financials
from forecaster.utils import extract_json


class EarningsAgent(BaseAgent):
    agent_id = "earnings"

    def run(
        self,
        symbol: str,
        thesis: str,
        forecast_id: int,
        financials: Optional[str] = None,
        instrument_type: Optional[str] = None,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        _, system_prompt = self.get_active_prompt()
        edgar_data = get_quarterly_financials(symbol)

        if edgar_data:
            data_source = "edgar"
            data_block = (
                f"Reported quarterly actuals from SEC EDGAR (data_source=edgar):\n"
                f"{json.dumps(edgar_data, indent=2)}\n\n"
                "Note: consensus EPS estimates and management guidance are NOT available from "
                "EDGAR (no free consensus-estimate feed exists) — quarterly_eps_estimates and "
                "management_guidance_eps are unavailable. Set beat_miss_trend and "
                "guidance_credibility to \"neutral\" and state the data gap in rationale rather "
                "than inferring them from training knowledge."
            )
        else:
            data_source = "financials_text" if financials else "training_knowledge"
            data_block = (
                f"No EDGAR XBRL data available for {symbol} (no CIK match or no XBRL EPS series — "
                f"common for non-US/foreign-private-issuer filers). data_source={data_source}.\n"
                f"Financials (free-text, from the position record): "
                f"{financials or 'not provided — assess from training knowledge'}\n\n"
                "State explicitly in rationale that this assessment is not based on structured "
                "time-series data."
            )

        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Instrument type: {instrument_type or 'not specified — infer from context'}\n"
                    f"Investment thesis: {thesis}\n\n"
                    f"{data_block}\n\n"
                    "Assess the earnings trajectory and FCF generation per the task and output_schema "
                    "in your system prompt."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=4096)
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
            earnings_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
