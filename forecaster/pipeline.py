"""
Forecast pipeline orchestrator.

Decomposes a position's thesis + risks into independently forecast
Critical/High-impact sub-questions, then aggregates them into a
buy/sell/hold/pass recommendation. Four stages (see
C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md):

  A. Decompose (once)        — QuestionDefinitionAgent
  B. Symbol context (once)   — MacroQ, RiskJudge, Earnings, PrimarySource,
                                Momentum/Trend/Volume/TechnicalJudge
  C. Per-question forecast   — Elicitation -> Review -> ConfidenceJudge,
     (N <= 7 times)            fanned out in parallel across sub-questions
  D. Aggregate (once)        — AggregationAgent
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from forecaster.db import (
    db_cursor,
    insert_forecast_question,
    portfolio_db_cursor,
)

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


class ForecastPipeline:
    """Orchestrates the full decomposition-based forecasting pipeline for one position."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def run(self, symbol: str, question_horizon_days: int = 90, force: bool = False) -> Optional[int]:
        """
        Run the full pipeline for *symbol*. Returns the forecast id or None
        if the triage gate rejects the position. force=True bypasses the
        triage gate (manual re-runs, side-by-side model comparisons) --
        never used by the scheduled/batch path, only explicit single-symbol
        invocations.
        """
        from forecaster.agents.triage import TriageAgent
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        from forecaster.agents.macroq import MacroQAgent
        from forecaster.agents.risk_judge import RiskJudgeAgent
        from forecaster.agents.research.earnings import EarningsAgent
        from forecaster.agents.research.primary_source import PrimarySourceAgent
        from forecaster.agents.technical.momentum import MomentumAgent
        from forecaster.agents.technical.trend import TrendAgent
        from forecaster.agents.technical.volume import VolumeAgent
        from forecaster.agents.technical.judge import TechnicalJudgeAgent
        from forecaster.agents.aggregation import AggregationAgent
        from forecaster.talib_preprocess import get_technical_context

        # Step 1 - triage gate (gates on prior adjusted_score magnitude, not
        # the retired v1 compound_conviction)
        prior_adjusted_score = self._get_prior_adjusted_score(symbol)
        if not force and not TriageAgent().run(prior_adjusted_score):
            logger.info(
                "Triage rejected %s (prior_adjusted_score=%.2f)",
                symbol, prior_adjusted_score or 0,
            )
            return None
        elif force and prior_adjusted_score is not None and abs(prior_adjusted_score) < TriageAgent.THRESHOLD:
            logger.info(
                "Triage would reject %s (prior_adjusted_score=%.2f) -- proceeding anyway (force=True)",
                symbol, prior_adjusted_score,
            )

        position = self._get_position_context(symbol)

        forecast_date = date.today()
        resolution_date = forecast_date + timedelta(days=question_horizon_days)
        forecast_id = self._insert_partial_forecast(symbol, forecast_date, resolution_date)

        try:
            # Stage A - decompose thesis + risks into scorable sub-questions
            q_result = QuestionDefinitionAgent().run(
                symbol=symbol, position=position,
                forecast_id=forecast_id,
            )
            questions = q_result.output.get("questions") or []
            monitor_list = q_result.output.get("monitor_list") or []
            nearterm_count = q_result.output.get("nearterm_critical_high_count")

            for question in questions:
                question["id"] = insert_forecast_question(
                    forecast_id,
                    question_type=question.get("type"),
                    question_text=question.get("question_text"),
                    resolution_criteria=question.get("resolution_criteria"),
                    resolution_date=self._parse_date(question.get("resolution_date")),
                    resolution_source=question.get("resolution_source"),
                    evidence_source=question.get("evidence_source"),
                    impact_direction=question.get("impact_direction"),
                    impact_magnitude=question.get("impact_magnitude"),
                    decomposition_rationale=question.get("rationale"),
                )

            # Stage B - shared symbol-level evidence
            macro_result = MacroQAgent().run(forecast_id=forecast_id)
            macro_state_id: Optional[int] = macro_result.output.get("root_macro_state_id")

            root_nodes = macro_result.output.get("nodes") or [{}]
            macro_summary = root_nodes[0].get("composite_rationale", "")
            risk_result = RiskJudgeAgent().run(
                symbol=symbol, thesis=position["thesis"], macro_summary=macro_summary,
                drawdown_threshold=position.get("drawdown_threshold"),
                nearterm_critical_high_count=nearterm_count,
                business=position.get("business"),
                competitive_landscape=position.get("competitive_landscape"),
                financials=position.get("financials"),
                forecast_id=forecast_id, macro_state_id=macro_state_id,
            )

            # A price-data-source failure (e.g. this portfolio's "TICKER EXCHANGE"
            # notation for foreign listings -- "MSI LSE" -- isn't a literal symbol
            # either IBKR or Yahoo accepts) must not be fatal to the whole pipeline:
            # question_definition/macroq/risk_judge already ran and cost real money
            # by this point, and a missing technical evidence source is exactly the
            # kind of gap elicitation.md is already designed to treat as neutral and
            # disclose, not a reason to discard everything and produce no forecast.
            tech_context = None
            try:
                tech_context = get_technical_context(symbol)
            except Exception as exc:
                logger.warning(
                    "No technical/price data available for %s (%s) -- skipping "
                    "Momentum/Trend/Volume/TechnicalJudge for this run",
                    symbol, exc,
                )

            earnings_result = primary_result = None
            if self._is_equity_like(position.get("instrument_type")):
                earnings_result, primary_result = self._run_parallel([
                    lambda: EarningsAgent().run(
                        symbol=symbol, thesis=position["thesis"], financials=position.get("financials"),
                        instrument_type=position.get("instrument_type"),
                        forecast_id=forecast_id, macro_state_id=macro_state_id),
                    lambda: PrimarySourceAgent().run(
                        symbol=symbol, thesis=position["thesis"], financials=position.get("financials"),
                        instrument_type=position.get("instrument_type"),
                        forecast_id=forecast_id, macro_state_id=macro_state_id),
                ])
            else:
                logger.info(
                    "Skipping Financial/PrimarySource for %s (instrument_type=%r has no "
                    "issuer earnings/filings)", symbol, position.get("instrument_type"),
                )

            momentum_r = trend_r = volume_r = tech_judge_result = None
            if tech_context is not None:
                momentum_r, trend_r, volume_r = self._run_parallel([
                    lambda: MomentumAgent().run(
                        symbol=symbol, tech_context=tech_context,
                        forecast_id=forecast_id, macro_state_id=macro_state_id),
                    lambda: TrendAgent().run(
                        symbol=symbol, tech_context=tech_context,
                        forecast_id=forecast_id, macro_state_id=macro_state_id),
                    lambda: VolumeAgent().run(
                        symbol=symbol, tech_context=tech_context,
                        forecast_id=forecast_id, macro_state_id=macro_state_id),
                ])
                tech_judge_result = TechnicalJudgeAgent().run(
                    tech_results=[momentum_r, trend_r, volume_r],
                    forecast_id=forecast_id, macro_state_id=macro_state_id,
                )

            symbol_context = {
                "macro": macro_result.output,
                "risk": risk_result.output,
                "earnings": earnings_result.output if earnings_result else {},
                "primary_source": primary_result.output if primary_result else {},
                "momentum": momentum_r.output if momentum_r else {},
                "trend": trend_r.output if trend_r else {},
                "volume": volume_r.output if volume_r else {},
                "technical_judge": tech_judge_result.output if tech_judge_result else {},
            }

            # Stage C - forecast each sub-question independently, fanned out in parallel
            questions = self._run_parallel([
                (lambda q=question: self._forecast_question(
                    symbol, q, symbol_context, position, forecast_id, macro_state_id
                ))
                for question in questions
            ])

            # Stage D - aggregate into a recommendation
            AggregationAgent().run(
                questions=questions,
                monitor_list=monitor_list,
                risk_floor_output=risk_result.output,
                asymmetric_rating=position.get("asymmetric_rating"),
                forecast_id=forecast_id, macro_state_id=macro_state_id,
            )

            logger.info("Pipeline complete for %s (forecast_id=%d)", symbol, forecast_id)
            return forecast_id

        except Exception:
            logger.exception("Pipeline failed for %s (forecast_id=%d)", symbol, forecast_id)
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _forecast_question(
        self,
        symbol: str,
        question: dict,
        symbol_context: dict,
        position: dict,
        forecast_id: int,
        macro_state_id: Optional[int],
    ) -> dict:
        """Runs elicitation -> review -> confidence_judge for one sub-question."""
        from forecaster.agents.elicitation import ElicitationAgent
        from forecaster.agents.review import ReviewAgent
        from forecaster.agents.confidence_judge import ConfidenceJudgeAgent

        elicitation_result = ElicitationAgent().run(
            symbol=symbol, question=question, symbol_context=symbol_context,
            question_id=question["id"], forecast_id=forecast_id, position=position,
            macro_state_id=macro_state_id,
        )
        review_result = ReviewAgent().run(
            question=question, elicitation_output=elicitation_result.output,
            symbol_context=symbol_context, question_id=question["id"],
            forecast_id=forecast_id, macro_state_id=macro_state_id,
        )
        confidence_result = ConfidenceJudgeAgent().run(
            elicitation_output=elicitation_result.output,
            review_output=review_result.output,
            question_id=question["id"], forecast_id=forecast_id,
            macro_state_id=macro_state_id,
        )
        question["final_probability"] = confidence_result.output.get("final_probability")
        question["elicitation_output"] = elicitation_result.output
        question["review_output"] = review_result.output
        question["confidence_output"] = confidence_result.output
        return question

    def _get_prior_adjusted_score(self, symbol: str) -> Optional[float]:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT adjusted_score
                FROM forecasts
                WHERE symbol = %s AND adjusted_score IS NOT NULL
                ORDER BY forecast_date DESC
                LIMIT 1
                """,
                (symbol,),
            )
            row = cur.fetchone()
            return float(row[0]) if row else None

    def _get_position_context(self, symbol: str) -> dict:
        cols = [
            "investment_thesis", "risks", "business", "competitive_landscape", "financials",
            "hold_period", "hold_period_rationale", "name", "label", "type", "asymmetric_rating",
            "risk_level", "risk_level_rationale", "tags", "source_name", "source_link",
            "profile_change_log", "profile_confidence", "profile_rationale", "profile_model",
            "thesis_test_date", "thesis_list", "thesis_list_rationale",
            "drawdown_threshold",
        ]
        with portfolio_db_cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(cols)} FROM positions WHERE symbol = %s",
                (symbol,),
            )
            row = cur.fetchone()
        if not row:
            return {"thesis": ""}
        position = dict(zip(cols, row))
        for k in ("drawdown_threshold", "profile_confidence"):
            if isinstance(position.get(k), Decimal):
                position[k] = float(position[k])
        if isinstance(position.get("thesis_test_date"), date):
            position["thesis_test_date"] = position["thesis_test_date"].isoformat()
        position["thesis"] = position.pop("investment_thesis") or ""
        position["instrument_type"] = position.pop("type") or None
        return position

    # Instrument types with no issuer earnings/SEC filings of their own — Financial
    # and PrimarySource agents have nothing to analyze for these (an ETF's sponsor
    # doesn't report EPS for the fund; FX/futures/rates products have no issuer at
    # all). Unrecognized or blank types default to equity treatment (current/legacy
    # positions may predate the `type` column being populated).
    #
    # NOTE: in this portfolio, `type` is populated for only ~35% of positions and,
    # where populated, is actually a sector/theme tag ("Commodity" includes real
    # single-name operating companies like LIN, CVX, EQT, FNV, NTR, MP -- alongside
    # real commodity ETFs like DBC/GDX/XME), not a clean instrument-type taxonomy.
    # "commodity" was found to incorrectly skip Financial/PrimarySource for LIN
    # itself (a real EDGAR filer) and is deliberately excluded from this list --
    # only types that are unambiguous in the real data are skipped. Real ETFs with
    # blank `type` (SPY, TLT, GLD, sector SPDRs) fall through to the prompt-level
    # guard in earnings.md/primary_source.md instead, since this column can't
    # reliably gate them.
    _NON_EQUITY_TYPES = {"fx", "currency", "future", "futures", "forward", "crypto", "fixed income"}

    @classmethod
    def _is_equity_like(cls, instrument_type: Optional[str]) -> bool:
        if not instrument_type:
            return True
        return instrument_type.strip().lower() not in cls._NON_EQUITY_TYPES

    def _parse_date(self, value: Optional[str]) -> Optional[str]:
        """Validate an LLM-produced date string; return None if malformed
        rather than letting a bad string reach the DATE column."""
        if not value:
            return None
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            logger.warning("Discarding malformed resolution_date: %r", value)
            return None

    def _insert_partial_forecast(self, symbol: str, forecast_date: date, resolution_date: date) -> int:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO forecasts (symbol, forecast_date, resolution_date)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (symbol, forecast_date.isoformat(), resolution_date.isoformat()),
            )
            row = cur.fetchone()
            if not row:
                raise PipelineError(f"Failed to insert partial forecast row for {symbol}")
            return int(row[0])

    def _run_parallel(self, callables: list) -> list:
        """Execute callables concurrently; return results in submission order."""
        results = [None] * len(callables)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {pool.submit(fn): i for i, fn in enumerate(callables)}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()
        return results
