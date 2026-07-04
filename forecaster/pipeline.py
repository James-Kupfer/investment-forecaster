"""
Forecast pipeline orchestrator.

Runs all 13 agents in sequence/parallel for a given symbol and writes
results to the forecasts and llm_call_log tables.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Optional

from forecaster.db import db_cursor, update_forecast_columns

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


class ForecastPipeline:
    """Orchestrates the full 13-agent forecasting pipeline for one position."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def run(self, symbol: str, question_horizon_days: int = 90) -> Optional[int]:
        """
        Run the full pipeline for *symbol*.  Returns the forecast id or None
        if the triage gate rejects the position.
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
        from forecaster.agents.technical.pattern import PatternAgent
        from forecaster.agents.technical.judge import TechnicalJudgeAgent
        from forecaster.agents.elicitation import ElicitationAgent
        from forecaster.agents.review import ReviewAgent
        from forecaster.agents.confidence_judge import ConfidenceJudgeAgent
        from forecaster.agents.aggregation import AggregationAgent
        from forecaster.talib_preprocess import get_technical_context

        # Step 1 - triage gate
        prior_conviction = self._get_prior_conviction(symbol)
        if not TriageAgent().run(prior_conviction):
            logger.info("Triage rejected %s (prior_conviction=%.2f)", symbol, prior_conviction or 0)
            return None

        thesis = self._get_thesis(symbol)

        # Insert partial forecasts row so every llm_call_log entry has a valid FK.
        forecast_date = date.today()
        resolution_date = forecast_date + timedelta(days=question_horizon_days)
        forecast_id = self._insert_partial_forecast(symbol, forecast_date, resolution_date)

        try:
            # Step 2 - question definition
            q_result = QuestionDefinitionAgent().run(
                symbol=symbol, thesis=thesis,
                horizon_days=question_horizon_days, forecast_id=forecast_id,
            )
            question_text = q_result.output.get("question") or f"Will {symbol} achieve its thesis?"

            # Step 3 - MacroQ (writes macro_state rows; returns root macro_state id)
            macro_result = MacroQAgent().run(forecast_id=forecast_id)
            macro_state_id: Optional[int] = macro_result.output.get("root_macro_state_id")

            # Step 4 - risk judge
            root_nodes = macro_result.output.get("nodes") or [{}]
            macro_summary = root_nodes[0].get("composite_rationale", "")
            risk_result = RiskJudgeAgent().run(
                symbol=symbol, thesis=thesis, macro_summary=macro_summary,
                forecast_id=forecast_id, macro_state_id=macro_state_id,
            )

            # Step 5 - earnings + primary source (parallel); fetch TA context alongside
            tech_context = get_technical_context(symbol)
            earnings_result, primary_result = self._run_parallel([
                lambda: EarningsAgent().run(
                    symbol=symbol, thesis=thesis,
                    forecast_id=forecast_id, macro_state_id=macro_state_id),
                lambda: PrimarySourceAgent().run(
                    symbol=symbol, thesis=thesis,
                    forecast_id=forecast_id, macro_state_id=macro_state_id),
            ])

            # Step 6 - four technical agents (parallel), then technical judge
            momentum_r, trend_r, volume_r, pattern_r = self._run_parallel([
                lambda: MomentumAgent().run(
                    symbol=symbol, tech_context=tech_context,
                    forecast_id=forecast_id, macro_state_id=macro_state_id),
                lambda: TrendAgent().run(
                    symbol=symbol, tech_context=tech_context,
                    forecast_id=forecast_id, macro_state_id=macro_state_id),
                lambda: VolumeAgent().run(
                    symbol=symbol, tech_context=tech_context,
                    forecast_id=forecast_id, macro_state_id=macro_state_id),
                lambda: PatternAgent().run(
                    symbol=symbol, tech_context=tech_context,
                    forecast_id=forecast_id, macro_state_id=macro_state_id),
            ])
            tech_judge_result = TechnicalJudgeAgent().run(
                tech_results=[momentum_r, trend_r, volume_r, pattern_r],
                forecast_id=forecast_id, macro_state_id=macro_state_id,
            )

            all_context = {
                "symbol": symbol,
                "question": question_text,
                "macro": macro_result.output,
                "risk": risk_result.output,
                "earnings": earnings_result.output if earnings_result else {},
                "primary_source": primary_result.output if primary_result else {},
                "momentum": momentum_r.output if momentum_r else {},
                "trend": trend_r.output if trend_r else {},
                "volume": volume_r.output if volume_r else {},
                "pattern": pattern_r.output if pattern_r else {},
                "technical_judge": tech_judge_result.output if tech_judge_result else {},
            }

            # Step 7 - elicitation
            elicitation_result = ElicitationAgent().run(
                symbol=symbol, question=question_text, all_context=all_context,
                forecast_id=forecast_id, macro_state_id=macro_state_id,
            )

            # Step 8 - review
            review_result = ReviewAgent().run(
                elicitation_output=elicitation_result.output,
                all_context=all_context,
                forecast_id=forecast_id, macro_state_id=macro_state_id,
            )

            # Step 9 - confidence judge
            confidence_result = ConfidenceJudgeAgent().run(
                elicitation_output=elicitation_result.output,
                review_output=review_result.output,
                forecast_id=forecast_id, macro_state_id=macro_state_id,
            )

            # Step 10 - aggregation
            all_context["elicitation"] = elicitation_result.output
            all_context["review"] = review_result.output
            all_context["confidence_judge"] = confidence_result.output
            AggregationAgent().run(
                all_outputs=all_context,
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

    def _get_prior_conviction(self, symbol: str) -> Optional[float]:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT TOP 1 compound_conviction
                FROM forecasts
                WHERE symbol = ? AND compound_conviction IS NOT NULL
                ORDER BY forecast_date DESC
                """,
                symbol,
            )
            row = cur.fetchone()
            return float(row[0]) if row else None

    def _get_thesis(self, symbol: str) -> str:
        with db_cursor() as cur:
            cur.execute(
                "SELECT investment_thesis FROM positions WHERE symbol = ?",
                symbol,
            )
            row = cur.fetchone()
            return (row[0] or "") if row else ""

    def _insert_partial_forecast(self, symbol: str, forecast_date: date, resolution_date: date) -> int:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO forecasts (symbol, forecast_date, resolution_date)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?)
                """,
                symbol,
                forecast_date.isoformat(),
                resolution_date.isoformat(),
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
