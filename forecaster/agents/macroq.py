import json
import logging
import uuid
from datetime import date
from typing import Optional

from forecaster.agents.base import BaseAgent, AgentResult
from forecaster.db import db_cursor, update_forecast_columns
from forecaster.market_data import MarketDataFetcher
from forecaster.utils import extract_json

logger = logging.getLogger(__name__)

# (yfinance_ticker, ibkr_symbol, ibkr_sec_type)
# ibkr_symbol=None means IBKR doesn't carry this instrument; yfinance is used directly.
_MACRO_TICKERS: dict[str, tuple[str, str | None, str | None]] = {
    "vix":       ("^VIX",      "VIX", "IND"),
    "dxy":       ("DX-Y.NYB",  None,  None),   # not in IBKR
    "rates_10y": ("^TNX",      None,  None),   # not in IBKR
    "rates_2y":  ("^IRX",      None,  None),   # not in IBKR
    "xlk":       ("XLK",       "XLK", "STK"),
    "xle":       ("XLE",       "XLE", "STK"),
    "xme":       ("XME",       "XME", "STK"),
    "xlf":       ("XLF",       "XLF", "STK"),
    "xlv":       ("XLV",       "XLV", "STK"),
    "xli":       ("XLI",       "XLI", "STK"),
}

_fetcher = MarketDataFetcher()


def _fetch_macro_snapshot() -> dict:
    data = {}
    for key, (yf_ticker, ibkr_sym, ibkr_sec) in _MACRO_TICKERS.items():
        try:
            hist = _fetcher.fetch_ohlcv(
                symbol=ibkr_sym if ibkr_sym else yf_ticker,
                period_yf="1mo",
                ibkr_period="ONE_MONTH",
                sec_type=ibkr_sec or "STK",
            )
            if hist.empty:
                data[key] = {"price": None, "return_1mo": None}
                continue
            latest = float(hist["Close"].iloc[-1])
            earliest = float(hist["Close"].iloc[0])
            ret = (latest - earliest) / earliest if earliest != 0 else 0.0
            data[key] = {"price": round(latest, 4), "return_1mo": round(ret, 4)}
        except Exception as exc:
            logger.warning("Failed to fetch %s (%s): %s", key, yf_ticker, exc)
            data[key] = {"price": None, "return_1mo": None}
    return data


class MacroQAgent(BaseAgent):
    agent_id = "macroq"
    model = "claude-sonnet-4-6"

    def run(
        self,
        forecast_id: Optional[int] = None,
        macro_state_id: Optional[int] = None,
    ) -> AgentResult:
        prompt_version_id, system_prompt = self.get_active_prompt()
        snapshot = _fetch_macro_snapshot()
        messages = [
            {
                "role": "user",
                "content": (
                    "Current macro indicators (price + 1-month return):\n"
                    f"{json.dumps(snapshot, indent=2)}\n\n"
                    "Produce a macro decision tree. Root node_id must start with 'root_'. "
                    "Each node: node_id, parent_node_id (null for root), composite_score (0-1), "
                    "composite_confidence (high/medium/low), composite_rationale, "
                    "rates_signal, rates_confidence, dxy_signal, dxy_confidence, "
                    "vix_signal, vix_confidence, sector_signal, sector_confidence, node_rationale."
                ),
            }
        ]
        result = self.call(messages, system=system_prompt, max_tokens=2048)
        self.log_call(result, forecast_id=forecast_id)

        root_db_id = self._persist_tree(result, prompt_version_id)
        result.output["root_macro_state_id"] = root_db_id

        if forecast_id and root_db_id:
            nodes = result.output.get("nodes") or []
            root_node = next((n for n in nodes if n.get("parent_node_id") is None), {})
            update_forecast_columns(
                forecast_id,
                macroq_node_id=(root_node.get("node_id") or "")[:50],
                macroq_p=root_node.get("composite_score"),
                macroq_confidence=root_node.get("composite_confidence"),
                macroq_rationale=root_node.get("composite_rationale"),
                macroq_output=json.dumps(result.output),
            )
        return result

    def _persist_tree(self, result: AgentResult, prompt_version_id: int) -> Optional[int]:
        nodes = result.output.get("nodes") or []
        if not nodes:
            return None
        today = date.today().isoformat()
        run_suffix = uuid.uuid4().hex[:6]
        root_db_id = None
        with db_cursor() as cur:
            for node in nodes:
                stable_node_id = f"{node.get('node_id', 'root')}_{run_suffix}"
                parent = (
                    f"{node['parent_node_id']}_{run_suffix}"
                    if node.get("parent_node_id")
                    else None
                )
                cur.execute(
                    """
                    INSERT INTO macro_state (
                        node_id, parent_node_id, macro_date,
                        composite_score, composite_confidence, composite_rationale,
                        rates_signal, rates_confidence,
                        dxy_signal, dxy_confidence,
                        vix_signal, vix_confidence,
                        sector_signal, sector_confidence,
                        node_rationale, executing_model, prompt_version_id
                    )
                    OUTPUT INSERTED.id
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    stable_node_id, parent, today,
                    node.get("composite_score", 0.5),
                    node.get("composite_confidence", "medium"),
                    node.get("composite_rationale") or "",
                    node.get("rates_signal"), node.get("rates_confidence"),
                    node.get("dxy_signal"), node.get("dxy_confidence"),
                    node.get("vix_signal"), node.get("vix_confidence"),
                    node.get("sector_signal"), node.get("sector_confidence"),
                    node.get("node_rationale") or "",
                    self.model, prompt_version_id,
                )
                row = cur.fetchone()
                if row and node.get("parent_node_id") is None:
                    root_db_id = int(row[0])
        return root_db_id

    def _parse_response(self, response) -> dict:
        text = response.content[0].text if response.content else ""
        return extract_json(text)
