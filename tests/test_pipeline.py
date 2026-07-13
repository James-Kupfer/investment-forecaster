"""
Unit tests for forecaster/pipeline.py helper logic that doesn't require a DB
or live API (full pipeline.run() is exercised via manual/live runs, not here).
"""
from __future__ import annotations

import pytest

from forecaster.pipeline import ForecastPipeline


class TestIsEquityLike:
    @pytest.mark.parametrize(
        "instrument_type",
        [None, "", "Stock", "Equity", "REIT", "ADR", "stock",
         # "Commodity" is deliberately equity-like: in the real portfolio it's a
         # sector/theme tag covering real single-name operating companies (LIN,
         # CVX, EQT, FNV, NTR, MP) alongside real commodity ETFs (DBC, GDX, XME) --
         # too ambiguous to gate on, so it defaults to running Financial/PrimarySource
         # rather than incorrectly skipping analysis for a real EDGAR filer like LIN.
         "Commodity", "commodity"],
    )
    def test_equity_and_blank_types_are_equity_like(self, instrument_type):
        assert ForecastPipeline._is_equity_like(instrument_type) is True

    @pytest.mark.parametrize(
        "instrument_type",
        ["FX", "fx", "Currency", "Future", "Futures", "Forward", "Crypto", "crypto",
         "Fixed Income", "fixed income"],
    )
    def test_non_equity_types_are_not_equity_like(self, instrument_type):
        assert ForecastPipeline._is_equity_like(instrument_type) is False

    def test_unrecognized_type_defaults_to_equity_like(self):
        assert ForecastPipeline._is_equity_like("SomeNewInstrumentType") is True
