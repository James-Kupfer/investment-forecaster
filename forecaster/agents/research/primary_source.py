import json
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import update_forecast_columns
from forecaster.edgar_client import fetch_filing_excerpt, get_insider_transactions, get_recent_filings
from forecaster.utils import extract_json


class PrimarySourceAgent(BaseAgent):
    agent_id = "primary_source"

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

        core_filings = get_recent_filings(symbol, forms=("10-K", "10-Q", "20-F"), limit=4)
        press_filings = get_recent_filings(symbol, forms=("8-K", "6-K"), limit=4)
        sec_filings = [
            {"source": f["form"], "quarter": f["filed"], "excerpt": fetch_filing_excerpt(f) or ""}
            for f in core_filings
        ]
        sec_filings = [f for f in sec_filings if f["excerpt"]]
        press_releases = [
            {"date": f["filed"], "excerpt": fetch_filing_excerpt(f) or ""}
            for f in press_filings
        ]
        press_releases = [p for p in press_releases if p["excerpt"]]
        insider_transactions = get_insider_transactions(symbol)
        if sec_filings or insider_transactions:
            data_source = "edgar"
            fallback_note = ""
        elif financials:
            data_source = "financials_text"
            fallback_note = (
                f"No EDGAR filings or insider transactions were found for {symbol} (no CIK match "
                f"or no usable filings — common for non-US/foreign-private-issuer symbols). "
                f"data_source={data_source}.\n"
                f"Financials (free-text, from the position record): {financials}\n\n"
                "Derive supporting_evidence/contradicting_evidence entries from this narrative "
                "where it supports a specific claim; note which entries were narrative-derived "
                "rather than pulled from a filing excerpt. insider_activity MUST be \"neutral\" — "
                "free-text financials carry no transaction-level data, so do not guess a buy/sell "
                "pattern from it. State explicitly that this assessment is not evidence-hierarchy-"
                "backed in the primary-source sense.\n\n"
            )
        else:
            data_source = "training_knowledge"
            fallback_note = (
                "If sec_filings and insider_transactions are both empty (no EDGAR CIK match, "
                "e.g. thinly-covered or non-US-filer symbols), state this explicitly and note "
                "the assessment falls back to training knowledge rather than primary sources.\n\n"
            )

        messages = [
            {
                "role": "user",
                "content": (
                    f"Symbol: {symbol}\n"
                    f"Instrument type: {instrument_type or 'not specified — infer from context'}\n"
                    f"Investment thesis: {thesis}\n\n"
                    f"data_source={data_source}\n\n"
                    f"sec_filings (10-K/10-Q/20-F excerpts from EDGAR): "
                    f"{json.dumps(sec_filings, indent=2)}\n\n"
                    f"press_releases (8-K/6-K excerpts from EDGAR, closest free proxy — many 8-Ks "
                    f"Item 2.02 exhibits ARE the earnings press release): "
                    f"{json.dumps(press_releases, indent=2)}\n\n"
                    f"earnings_transcripts: [] — not available; the SEC does not receive call "
                    f"transcripts and no free feed exists. Do not infer transcript content.\n\n"
                    f"investor_presentations: [] — not available from EDGAR.\n\n"
                    f"insider_transactions (Form 4 open-market buy/sell only, from EDGAR): "
                    f"{json.dumps(insider_transactions, indent=2)}\n\n"
                    "short_interest_trend: \"unavailable\" — FINRA/exchange data, not carried by "
                    "EDGAR. Exclude it from net_assessment weighting; do not guess a direction.\n\n"
                    f"{fallback_note}"
                    "Identify and weigh the available primary source evidence for and against the "
                    "thesis per the task and output_schema in your system prompt."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=8000)
        self.log_call(result, forecast_id=forecast_id, macro_state_id=macro_state_id)
        update_forecast_columns(
            forecast_id,
            primary_signal=(result.output.get("net_assessment") or "")[:200],
            primary_confidence=result.output.get("confidence"),
            primary_rationale=result.output.get("rationale"),
            primary_model=self.model,
            primary_prompt_version=result.prompt_version_id,
            primary_output=json.dumps(result.output),
        )
        return result

    def _parse_response(self, response) -> dict:
        text = self.extract_text_block(response) or ""
        return extract_json(text)
