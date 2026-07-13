"""
Unit tests for forecaster/edgar_client.py. All SEC network calls are mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forecaster import edgar_client


@pytest.fixture(autouse=True)
def _reset_caches():
    edgar_client._cik_map_cache = None
    edgar_client._company_facts_cache = {}
    edgar_client._last_request_ts = 0.0
    yield
    edgar_client._cik_map_cache = None
    edgar_client._company_facts_cache = {}


def _mock_get_json(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class TestGetCik:
    def test_finds_ticker_case_insensitive(self):
        payload = {"0": {"ticker": "LIN", "cik_str": 1707925}}
        with patch("requests.get", return_value=_mock_get_json(payload)):
            assert edgar_client.get_cik("lin") == "0001707925"

    def test_returns_none_when_not_found(self):
        payload = {"0": {"ticker": "LIN", "cik_str": 1707925}}
        with patch("requests.get", return_value=_mock_get_json(payload)):
            assert edgar_client.get_cik("NOPE") is None

    def test_caches_ticker_map_across_calls(self):
        payload = {"0": {"ticker": "LIN", "cik_str": 1707925}}
        with patch("requests.get", return_value=_mock_get_json(payload)) as mock_get:
            edgar_client.get_cik("LIN")
            edgar_client.get_cik("LIN")
            assert mock_get.call_count == 1


class TestQuarterlyFinancials:
    def _facts(self):
        return {
            "facts": {
                "us-gaap": {
                    "EarningsPerShareDiluted": {
                        "units": {
                            "USD/shares": [
                                {"start": "2024-01-01", "end": "2024-03-31", "val": 0.45, "filed": "2024-05-01"},
                                {"start": "2024-04-01", "end": "2024-06-30", "val": 0.48, "filed": "2024-08-01"},
                                # stale duplicate for same period, filed earlier — should be superseded
                                {"start": "2024-04-01", "end": "2024-06-30", "val": 0.40, "filed": "2024-07-01"},
                                # annual period — must be excluded (not ~1 quarter)
                                {"start": "2024-01-01", "end": "2024-12-31", "val": 1.90, "filed": "2025-02-01"},
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {"start": "2024-01-01", "end": "2024-03-31", "val": 90, "filed": "2024-05-01"},
                                {"start": "2024-04-01", "end": "2024-06-30", "val": 96, "filed": "2024-08-01"},
                            ]
                        }
                    },
                }
            }
        }

    def test_returns_none_without_cik(self):
        with patch.object(edgar_client, "get_cik", return_value=None):
            assert edgar_client.get_quarterly_financials("NOPE") is None

    def test_returns_none_without_eps_series(self):
        with patch.object(edgar_client, "get_cik", return_value="0001234567"), \
             patch.object(edgar_client, "get_company_facts", return_value={"facts": {"us-gaap": {}}}):
            assert edgar_client.get_quarterly_financials("ZZZ") is None

    def test_extracts_quarterly_series_and_dedupes_by_latest_filed(self):
        with patch.object(edgar_client, "get_cik", return_value="0001234567"), \
             patch.object(edgar_client, "get_company_facts", return_value=self._facts()):
            result = edgar_client.get_quarterly_financials("ZETA", n_quarters=4)
        assert result["quarters_available"] == 2
        assert result["quarterly_eps_actuals"] == [0.45, 0.48]  # dedup keeps latest-filed 0.48, not 0.40
        assert result["gaap_net_income"] == [90, 96]

    def test_missing_secondary_tag_yields_none_entries(self):
        facts = self._facts()
        del facts["facts"]["us-gaap"]["NetIncomeLoss"]
        with patch.object(edgar_client, "get_cik", return_value="0001234567"), \
             patch.object(edgar_client, "get_company_facts", return_value=facts):
            result = edgar_client.get_quarterly_financials("ZETA")
        assert result["gaap_net_income"] == [None, None]


class TestRecentFilings:
    def test_filters_by_form_and_respects_limit(self):
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-Q", "8-K", "10-K", "8-K"],
                    "accessionNumber": ["a1", "a2", "a3", "a4"],
                    "filingDate": ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"],
                    "primaryDocument": ["d1.htm", "d2.htm", "d3.htm", "d4.htm"],
                }
            }
        }
        with patch.object(edgar_client, "get_cik", return_value="0001234567"), \
             patch.object(edgar_client, "_get_json", return_value=submissions):
            out = edgar_client.get_recent_filings("ZETA", forms=("10-Q", "10-K"), limit=5)
        assert [f["form"] for f in out] == ["10-Q", "10-K"]

    def test_returns_empty_without_cik(self):
        with patch.object(edgar_client, "get_cik", return_value=None):
            assert edgar_client.get_recent_filings("NOPE") == []


class TestFetchFilingExcerpt:
    def test_strips_html_and_truncates(self):
        filing = {"accession": "0001234567-24-000001", "cik": "1234567", "primary_document": "d.htm"}
        html = "<html><body><script>ignored()</script><p>Hello world.</p></body></html>"
        with patch.object(edgar_client, "_get_text", return_value=html):
            excerpt = edgar_client.fetch_filing_excerpt(filing, max_chars=5)
        assert excerpt == "Hello"

    def test_returns_none_on_fetch_failure(self):
        filing = {"accession": "0001234567-24-000001", "cik": "1234567", "primary_document": "d.htm"}
        with patch.object(edgar_client, "_get_text", return_value=None):
            assert edgar_client.fetch_filing_excerpt(filing) is None


class TestInsiderTransactions:
    _FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <officerTitle>Chief Financial Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1000</value></transactionShares></transactionAmounts>
      <transactionDate><value>2024-06-01</value></transactionDate>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>500</value></transactionShares></transactionAmounts>
      <transactionDate><value>2024-06-02</value></transactionDate>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

    def test_parses_purchase_and_skips_non_open_market_codes(self):
        filing = {"accession": "0001-24-000001", "cik": "1234567", "primary_document": "form4.xml"}
        with patch.object(edgar_client, "_get_text", return_value=self._FORM4_XML):
            out = edgar_client._parse_form4(filing)
        assert out == [{"role": "CFO", "action": "buy", "shares": 1000, "date": "2024-06-01"}]

    def test_get_insider_transactions_aggregates_across_filings(self):
        filing_list = [
            {"form": "4", "filed": "2024-06-01", "accession": "0001-24-000001", "primary_document": "form4.xml", "cik": "1234567"},
        ]
        with patch.object(edgar_client, "get_recent_filings", return_value=filing_list), \
             patch.object(edgar_client, "_get_text", return_value=self._FORM4_XML):
            out = edgar_client.get_insider_transactions("ZETA")
        assert len(out) == 1
        assert out[0]["action"] == "buy"


class TestNormalizeInsiderRole:
    @pytest.mark.parametrize(
        "is_director,is_officer,is_ten_pct,title,expected",
        [
            (False, True, False, "Chief Executive Officer", "CEO"),
            (False, True, False, "Chief Financial Officer", "CFO"),
            (False, True, False, "Chief Operating Officer", "COO"),
            (False, True, False, "EVP Sales", "EVP Sales"),
            (True, False, False, "", "Director"),
            (False, False, True, "", "10% Owner"),
            (False, False, False, "", "Insider"),
        ],
    )
    def test_role_mapping(self, is_director, is_officer, is_ten_pct, title, expected):
        assert edgar_client._normalize_insider_role(is_director, is_officer, is_ten_pct, title) == expected
