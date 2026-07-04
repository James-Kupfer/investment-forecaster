"""
Forecast pipeline orchestrator.

Runs all 13 agents in sequence/parallel for a given symbol and writes
results to the forecasts and llm_call_log tables.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from forecaster.db import db_cursor

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


class ForecastPipeline:
    """Orchestrates the full 13-agent forecasting pipeline for one position."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def run(self, symbol: str, question_horizon_days: int = 90) -> Optional[int]:
        """
        Run the full pipeline for *symbol*.  Returns the forecast_id or None
        if the triage gate rejects the position.
        """
        # Step 1 — triage gate
        from forecaster.agents.triage import TriageAgent
        prior_conviction = self._get_prior_conviction(symbol)
        if not TriageAgent().run(prior_conviction):
            logger.info("Triage rejected %s (prior_conviction=%.2f)", symbol, prior_conviction)
            return None

        # Insert partial forecasts row so all llm_call_log entries have a valid FK.
        forecast_id = self._insert_partial_forecast(symbol)

        try:
            # Step 2 — question definition
            # TODO: replace stub with QuestionDefinitionAgent().run(symbol, horizon_days)
            question_text = f"Will {symbol} achieve its thesis within {question_horizon_days} days?"
            self._update_forecast(forecast_id, question_text=question_text)

            # Step 3 — MacroQ (daily job writes to macro_state; pipeline reads latest row)
            macro_state_id = self._get_latest_macro_state_id()

            # Step 4 — risk judge
            # TODO: replace stub with RiskJudgeAgent().run(symbol, macro_state_id)

            # Step 5 — earnings + primary source (parallel)
            self._run_parallel([
                # TODO: lambda: EarningsAgent().run(symbol, forecast_id, macro_state_id),
                # TODO: lambda: PrimarySourceAgent().run(symbol, forecast_id, macro_state_id),
                lambda: None,
                lambda: None,
            ])

            # Step 6 — technical layer (parallel), then technical judge
            self._run_parallel([
                # TODO: lambda: MomentumAgent().run(symbol, forecast_id, macro_state_id),
                # TODO: lambda: TrendAgent().run(symbol, forecast_id, macro_state_id),
                # TODO: lambda: VolumeAgent().run(symbol, forecast_id, macro_state_id),
                # TODO: lambda: PatternAgent().run(symbol, forecast_id, macro_state_id),
                lambda: None,
                lambda: None,
                lambda: None,
                lambda: None,
            ])
            # TODO: TechnicalJudgeAgent().run(tech_results, forecast_id, macro_state_id)

            # Step 7 — elicitation
            # TODO: ElicitationAgent().run(symbol, forecast_id, macro_state_id)

            # Step 8 — review
            # TODO: ReviewAgent().run(symbol, forecast_id, macro_state_id)

            # Step 9 — confidence judge
            # TODO: ConfidenceJudgeAgent().run(forecast_id, macro_state_id)

            # Step 10 — aggregation
            # TODO: AggregationAgent().run(forecast_id, macro_state_id)
            # TODO: self._finalise_forecast(forecast_id, aggregation)

            logger.info("Pipeline complete for %s (forecast_id=%d)", symbol, forecast_id)
            return forecast_id

        except Exception:
            logger.exception("Pipeline failed for %s (forecast_id=%d)", symbol, forecast_id)
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_prior_conviction(self, symbol: str) -> Optional[float]:
        """Return compound_conviction from the most recent completed forecast, or None."""
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

    def _insert_partial_forecast(self, symbol: str) -> int:
        """Insert a stub forecasts row and return the new forecast_id."""
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO forecasts (symbol, forecast_date)
                OUTPUT INSERTED.forecast_id
                VALUES (?, CAST(GETDATE() AS DATE))
                """,
                symbol,
            )
            row = cur.fetchone()
            if not row:
                raise PipelineError(f"Failed to insert partial forecast row for {symbol}")
            return int(row[0])

    def _update_forecast(self, forecast_id: int, **kwargs) -> None:
        """UPDATE forecasts SET col=val,... WHERE forecast_id=?"""
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [forecast_id]
        with db_cursor() as cur:
            cur.execute(f"UPDATE forecasts SET {cols} WHERE forecast_id = ?", *values)

    def _get_latest_macro_state_id(self) -> Optional[int]:
        """Return id of the most recently written macro_state root node."""
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT TOP 1 id FROM macro_state
                WHERE parent_node_id IS NULL
                ORDER BY macro_date DESC, id DESC
                """
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def _run_parallel(self, callables: list) -> list:
        """Execute callables concurrently and return results in submission order."""
        results = [None] * len(callables)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {pool.submit(fn): i for i, fn in enumerate(callables)}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()
        return results
