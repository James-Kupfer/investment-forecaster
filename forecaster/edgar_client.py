"""
SEC EDGAR data fetch: real historical financials (XBRL company facts), filing
excerpts (10-K/10-Q/8-K/20-F/6-K), and insider transactions (Form 4).

EDGAR does NOT provide (no free source substitutes these, callers must
degrade gracefully when these come back empty/None):
  - consensus analyst EPS estimates or management guidance (no IBES-type feed)
  - earnings call transcripts (not filed with the SEC)
  - short interest (FINRA/exchange data, not SEC)
  - a forward-looking earnings calendar (EDGAR is a filing archive, not a calendar)

SEC requires a descriptive User-Agent identifying the requester (fair access
policy) — set SEC_EDGAR_USER_AGENT ("AppName/1.0 (contact@email)") in .env.
Requests are rate-limited to stay well under SEC's ~10 req/sec guidance.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date
from html.parser import HTMLParser
from typing import Optional
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

_DEFAULT_UA = "investment-forecaster/1.0 (unset-contact@investment-forecaster.local)"
_UA = os.getenv("SEC_EDGAR_USER_AGENT") or _DEFAULT_UA
if _UA == _DEFAULT_UA:
    logger.warning(
        "SEC_EDGAR_USER_AGENT not set — using a placeholder contact. SEC's fair-access policy "
        "wants a real identifying email; set SEC_EDGAR_USER_AGENT in .env (see .env.example)."
    )
_HEADERS = {"User-Agent": _UA, "Accept-Encoding": "gzip, deflate"}
_MIN_INTERVAL = 0.12  # stay under SEC's ~10 req/sec guidance

_last_request_ts = 0.0
_cik_map_cache: Optional[dict[str, str]] = None
_company_facts_cache: dict[str, Optional[dict]] = {}

_EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
_NET_INCOME_TAGS = ["NetIncomeLoss", "ProfitLoss"]
_OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
_CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForCapitalImprovements",
]
_REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]


def _throttle() -> None:
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_ts = time.monotonic()


def _get_json(url: str) -> Optional[dict]:
    _throttle()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.debug("EDGAR GET %s failed: %s", url, exc)
        return None


def _get_text(url: str) -> Optional[str]:
    _throttle()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.debug("EDGAR GET %s failed: %s", url, exc)
        return None


class _TextExtractor(HTMLParser):
    """Minimal HTML→plain-text stripper; skips script/style content."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.chunks.append(data.strip())


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", " ".join(parser.chunks)).strip()


def _load_cik_map() -> dict[str, str]:
    global _cik_map_cache
    if _cik_map_cache is not None:
        return _cik_map_cache
    data = _get_json("https://www.sec.gov/files/company_tickers.json")
    mapping: dict[str, str] = {}
    if data:
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = entry.get("cik_str")
            if ticker and cik is not None:
                mapping[ticker] = str(cik).zfill(10)
    _cik_map_cache = mapping
    return mapping


def get_cik(symbol: str) -> Optional[str]:
    """Return zero-padded 10-digit CIK for *symbol*, or None if not found."""
    return _load_cik_map().get(symbol.upper())


def get_company_facts(cik: str) -> Optional[dict]:
    if cik in _company_facts_cache:
        return _company_facts_cache[cik]
    facts = _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    _company_facts_cache[cik] = facts
    return facts


def _tag_series(facts: dict, tag_candidates: list[str], unit_candidates=("USD",)) -> list[dict]:
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for tag in tag_candidates:
        node = us_gaap.get(tag)
        if not node:
            continue
        units = node.get("units") or {}
        for unit_key in unit_candidates:
            entries = units.get(unit_key)
            if entries:
                return entries
    return []


def _quarterly_only(entries: list[dict]) -> list[dict]:
    """Keep ~3-month period entries, de-duplicated by period end (latest filed wins)."""
    by_end: dict[str, dict] = {}
    for e in entries:
        start, end = e.get("start"), e.get("end")
        if not start or not end:
            continue
        try:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            continue
        if not (80 <= days <= 100):
            continue
        prev = by_end.get(end)
        if prev is None or (e.get("filed", "") > prev.get("filed", "")):
            by_end[end] = e
    return sorted(by_end.values(), key=lambda e: e["end"])


def get_quarterly_financials(symbol: str, n_quarters: int = 4) -> Optional[dict]:
    """
    Real reported quarterly actuals from EDGAR XBRL company facts: EPS, GAAP net
    income, operating cash flow, capex, revenue. Returns None if the symbol has
    no EDGAR CIK or no usable XBRL EPS series (e.g. non-XBRL foreign filer) —
    callers must fall back to narrative/training-knowledge assessment in that case.

    Does NOT include consensus EPS estimates or management guidance — EDGAR has
    no such data; those fields must be treated as unavailable by the caller.
    """
    cik = get_cik(symbol)
    if not cik:
        return None
    facts = get_company_facts(cik)
    if not facts:
        return None

    eps_entries = _quarterly_only(_tag_series(facts, _EPS_TAGS, ("USD/shares",)))
    if not eps_entries:
        return None
    eps_entries = eps_entries[-n_quarters:]
    quarter_ends = [e["end"] for e in eps_entries]

    def series_for(tag_candidates: list[str]) -> list[Optional[float]]:
        by_end = {e["end"]: e.get("val") for e in _quarterly_only(_tag_series(facts, tag_candidates))}
        return [by_end.get(qe) for qe in quarter_ends]

    return {
        "quarters_available": len(quarter_ends),
        "quarter_end_dates": quarter_ends,
        "quarterly_eps_actuals": [e.get("val") for e in eps_entries],
        "gaap_net_income": series_for(_NET_INCOME_TAGS),
        "operating_cash_flow": series_for(_OCF_TAGS),
        "capex": series_for(_CAPEX_TAGS),
        "revenues": series_for(_REVENUE_TAGS),
    }


def get_recent_filings(
    symbol: str, forms: tuple[str, ...] = ("10-K", "10-Q", "8-K", "20-F", "6-K"), limit: int = 6
) -> list[dict]:
    """Recent filings of the given forms, newest first, with accession/document
    info needed to fetch the actual document text."""
    cik = get_cik(symbol)
    if not cik:
        return []
    data = _get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if not data:
        return []
    recent = (data.get("filings") or {}).get("recent") or {}
    forms_list = recent.get("form") or []
    accns = recent.get("accessionNumber") or []
    dates = recent.get("filingDate") or []
    docs = recent.get("primaryDocument") or []
    out = []
    for i, form in enumerate(forms_list):
        if form in forms and i < len(accns) and i < len(dates) and i < len(docs):
            out.append({
                "form": form,
                "filed": dates[i],
                "accession": accns[i],
                "primary_document": docs[i],
                "cik": cik,
            })
        if len(out) >= limit:
            break
    return out


def fetch_filing_excerpt(filing: dict, max_chars: int = 2500) -> Optional[str]:
    """Fetch and plain-text-strip the first *max_chars* of a filing document."""
    accn_nodash = filing["accession"].replace("-", "")
    cik_int = int(filing["cik"])
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/{filing['primary_document']}"
    raw = _get_text(url)
    if not raw:
        return None
    text = _strip_html(raw) if "<" in raw[:200] else raw
    return text[:max_chars]


def _normalize_insider_role(is_director: bool, is_officer: bool, is_ten_pct: bool, officer_title: str) -> str:
    title = (officer_title or "").lower()
    if "chief executive" in title:
        return "CEO"
    if "chief financial" in title:
        return "CFO"
    if "chief operating" in title:
        return "COO"
    if is_officer:
        return officer_title.strip() or "Officer"
    if is_director:
        return "Director"
    if is_ten_pct:
        return "10% Owner"
    return "Insider"


def _parse_form4(filing: dict) -> list[dict]:
    accn_nodash = filing["accession"].replace("-", "")
    cik_int = int(filing["cik"])
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/{filing['primary_document']}"
    raw = _get_text(url)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    def _find_text(elem, path) -> str:
        node = elem.find(path)
        return (node.text or "").strip() if node is not None and node.text else ""

    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    is_director = _find_text(rel, "isDirector") == "1" if rel is not None else False
    is_officer = _find_text(rel, "isOfficer") == "1" if rel is not None else False
    is_ten_pct = _find_text(rel, "isTenPercentOwner") == "1" if rel is not None else False
    officer_title = _find_text(rel, "officerTitle") if rel is not None else ""
    role = _normalize_insider_role(is_director, is_officer, is_ten_pct, officer_title)

    out = []
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = _find_text(tx, "transactionCoding/transactionCode")
        if code not in ("P", "S"):  # open-market purchase / sale only — skip grants, gifts, exercises
            continue
        shares_str = _find_text(tx, "transactionAmounts/transactionShares/value")
        tx_date = _find_text(tx, "transactionDate/value")
        try:
            shares = int(float(shares_str)) if shares_str else None
        except ValueError:
            shares = None
        out.append({
            "role": role,
            "action": "buy" if code == "P" else "sell",
            "shares": shares,
            "date": tx_date or None,
        })
    return out


def get_insider_transactions(symbol: str, limit: int = 8) -> list[dict]:
    """Open-market buy/sell transactions from recent Form 4 filings."""
    filings = get_recent_filings(symbol, forms=("4",), limit=limit * 2)
    out: list[dict] = []
    for filing in filings:
        try:
            out.extend(_parse_form4(filing))
        except Exception as exc:
            logger.debug("Form 4 parse failed for %s: %s", symbol, exc)
        if len(out) >= limit:
            break
    return out[:limit]
