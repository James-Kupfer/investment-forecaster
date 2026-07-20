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
     (N <= 20 times)            fanned out in parallel across sub-questions
  D. Aggregate (once)        — AggregationAgent
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from forecaster.db import (
    db_cursor,
    find_macro_state_id_by_node_prefix,
    get_forecast,
    get_forecast_questions,
    insert_forecast_question,
    portfolio_db_cursor,
)

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


def _json_safe_question(row: dict) -> dict:
    """A forecast_questions row straight from psycopg2 carries date and
    Decimal values (resolution_date, elicitation_p, final_probability,
    rationale_quality_score, brier, ...) that every agent's json.dumps(question)
    call chokes on -- a freshly-decomposed question dict never has this problem
    since it comes from parsed LLM JSON (plain str/float already). Only
    resurfaces for questions reconstructed from the DB during a resume."""
    safe = {}
    for key, value in row.items():
        if isinstance(value, (date, datetime)):
            safe[key] = value.isoformat()
        elif isinstance(value, Decimal):
            safe[key] = float(value)
        else:
            safe[key] = value
    return safe


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

        return self._execute(symbol, forecast_id, position)

    def resume(self, forecast_id: int) -> Optional[int]:
        """
        Resume an existing, incomplete forecast_id -- skips every stage whose
        sentinel column is already non-NULL and re-runs only what's missing.
        Never triages (this is a continuation of an already-approved run, not
        a new triage decision) and never creates a new forecasts row.

        Re-fetches position context fresh from investment_portfolio for
        whichever stages are about to be (re)run -- stages already completed
        in the original run were computed against the position context as of
        THAT run and are not recomputed even if the thesis/risks text has
        since changed. If the thesis changed materially, use a fresh run()
        instead; resume() is scoped to transient-failure recovery.
        """
        row = get_forecast(forecast_id)
        if row is None:
            raise PipelineError(f"No forecasts row with id={forecast_id}")
        if row["recommendation"] is not None:
            logger.info(
                "forecast_id=%d (%s) already complete (recommendation=%r) -- nothing to resume",
                forecast_id, row["symbol"], row["recommendation"],
            )
            return forecast_id

        logger.warning(
            "Resuming forecast_id=%d (%s) against CURRENT position context -- stages "
            "already completed in the original run were computed against the position "
            "context as of that run and are not recomputed even if the thesis/risks "
            "text has since changed.",
            forecast_id, row["symbol"],
        )
        position = self._get_position_context(row["symbol"])
        return self._execute(row["symbol"], forecast_id, position)

    def _execute(self, symbol: str, forecast_id: int, position: dict) -> Optional[int]:
        """Shared stage body for both a fresh run() and a resume(). Each stage
        checks the current DB state for forecast_id and either reconstructs
        already-completed work from stored JSON or runs the agent(s) as usual
        -- for a freshly-inserted row every sentinel is NULL, so this is a
        plain full run with zero special-casing."""
        from forecaster.agents.aggregation import AggregationAgent

        try:
            state = get_forecast(forecast_id)

            # Stage A - decompose thesis + risks into scorable sub-questions
            questions, monitor_list, nearterm_count = self._stage_a(symbol, position, forecast_id, state)

            # Stage B - shared symbol-level evidence
            symbol_context, risk_result, macro_state_id = self._stage_b(
                symbol, position, forecast_id, state, nearterm_count,
            )

            # Stage C - forecast each sub-question independently, fanned out in parallel
            questions, to_rerun = self._load_or_init_stage_c(questions)
            if to_rerun:
                self._run_parallel([
                    (lambda q=question: self._forecast_question(
                        symbol, q, symbol_context, position, forecast_id, macro_state_id
                    ))
                    for question in to_rerun
                ])
                # _forecast_question mutates each dict in place and returns it --
                # `questions` (which to_rerun's items are also references into)
                # already reflects the updates, no reassignment needed.

            # Stage D - aggregate into a recommendation
            state = get_forecast(forecast_id)
            if state["recommendation"] is None:
                AggregationAgent().run(
                    questions=questions,
                    monitor_list=monitor_list,
                    risk_floor_output=risk_result.output,
                    asymmetric_rating=position.get("asymmetric_rating"),
                    forecast_id=forecast_id, macro_state_id=macro_state_id,
                )
            else:
                logger.info("Stage D already complete for forecast_id=%d, skipping aggregation", forecast_id)

            logger.info("Pipeline complete for %s (forecast_id=%d)", symbol, forecast_id)
            return forecast_id

        except Exception:
            logger.exception("Pipeline failed for %s (forecast_id=%d)", symbol, forecast_id)
            raise

    def _stage_a(self, symbol: str, position: dict, forecast_id: int, state: dict) -> tuple:
        """Returns (questions, monitor_list, nearterm_critical_high_count).
        Stage-A completion is judged by whether forecast_questions rows exist
        for this forecast_id, NOT by forecasts.question_def_output -- that
        column is written unconditionally by QuestionDefinitionAgent (even
        json.dumps({}) on a swallowed LLM failure is non-NULL), so it can't
        distinguish "succeeded" from "failed and produced nothing"."""
        from forecaster.agents.question_definition import QuestionDefinitionAgent

        existing_rows = get_forecast_questions(forecast_id)
        stored_output = json.loads(state["question_def_output"]) if state["question_def_output"] else {}
        stored_questions = stored_output.get("questions") or []

        if not stored_questions:
            if existing_rows:
                raise PipelineError(
                    f"forecast_id={forecast_id}: {len(existing_rows)} forecast_questions rows "
                    f"exist but question_def_output has no questions -- refusing to resume "
                    f"(cannot safely correlate rows to a decomposition)"
                )
            q_result = QuestionDefinitionAgent().run(symbol=symbol, position=position, forecast_id=forecast_id)
            questions = q_result.output.get("questions") or []
            monitor_list = q_result.output.get("monitor_list") or []
            nearterm_count = q_result.output.get("nearterm_critical_high_count")
            for question in questions:
                question["id"] = insert_forecast_question(forecast_id, **self._question_insert_kwargs(question))
            return questions, monitor_list, nearterm_count

        # Refetch state's monitor_list/nearterm_count fresh -- both are written
        # by QuestionDefinitionAgent alongside question_def_output, so they're
        # already current in `state` for a resume.
        monitor_list = json.loads(state["monitor_list"]) if state["monitor_list"] else (stored_output.get("monitor_list") or [])
        nearterm_count = state["nearterm_critical_high_count"]

        if len(existing_rows) < len(stored_questions):
            # A DB-connectivity blip during the original insert loop (a plain
            # sequential `for`, one INSERT per question) can crash mid-loop
            # after question_def_output was already committed but before every
            # row landed. Insert exactly the missing tail, in original list
            # order -- never re-call the LLM here, that would silently produce
            # a different decomposition and duplicate/orphaned rows.
            logger.warning(
                "forecast_id=%d: question_def_output lists %d questions but only %d "
                "forecast_questions rows exist -- repairing the missing inserts without "
                "re-running QuestionDefinitionAgent", forecast_id, len(stored_questions), len(existing_rows),
            )
            for question in stored_questions[len(existing_rows):]:
                question["id"] = insert_forecast_question(forecast_id, **self._question_insert_kwargs(question))
            existing_rows = get_forecast_questions(forecast_id)
        elif len(existing_rows) > len(stored_questions):
            raise PipelineError(
                f"forecast_id={forecast_id}: {len(existing_rows)} forecast_questions rows but "
                f"question_def_output lists only {len(stored_questions)} -- refusing to resume "
                f"(cannot safely correlate rows to questions)"
            )

        return [_json_safe_question(row) for row in existing_rows], monitor_list, nearterm_count

    def _stage_b(
        self, symbol: str, position: dict, forecast_id: int, state: dict, nearterm_count,
    ) -> tuple:
        """Returns (symbol_context, risk_result, macro_state_id). Each Stage-B
        agent is judged solely by its own sentinel column -- a resume never
        re-runs an agent whose sentinel is already non-NULL, and never skips
        one whose eligibility gate (_is_equity_like / tech_context available)
        currently passes just because a sibling agent already succeeded."""
        from forecaster.agents.macroq import MacroQAgent
        from forecaster.agents.risk_judge import RiskJudgeAgent
        from forecaster.agents.research.earnings import EarningsAgent
        from forecaster.agents.research.primary_source import PrimarySourceAgent
        from forecaster.agents.technical.momentum import MomentumAgent
        from forecaster.agents.technical.trend import TrendAgent
        from forecaster.agents.technical.volume import VolumeAgent
        from forecaster.agents.technical.judge import TechnicalJudgeAgent
        from forecaster.talib_preprocess import get_technical_context

        if state["macroq_p"] is None:
            macro_result = MacroQAgent().run(forecast_id=forecast_id)
            macro_state_id: Optional[int] = macro_result.output.get("root_macro_state_id")
        else:
            macro_state_id = self._recover_macro_state_id(state)
            macro_result = self._reconstruct_agent_result("macroq", None, state["macroq_output"])

        if state["invq2_floor"] is None:
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
        else:
            risk_result = self._reconstruct_agent_result(
                "risk_judge", state["risk_judge_model"], state["risk_judge_output"])

        # A price-data-source failure (e.g. this portfolio's "TICKER EXCHANGE"
        # notation for foreign listings -- "MSI LSE" -- isn't a literal symbol
        # either IBKR or Yahoo accepts) must not be fatal to the whole pipeline:
        # question_definition/macroq/risk_judge already ran and cost real money
        # by this point, and a missing technical evidence source is exactly the
        # kind of gap elicitation.md is already designed to treat as neutral and
        # disclose, not a reason to discard everything and produce no forecast.
        # Re-fetched fresh on every resume (cheap price lookup, not an LLM call).
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
            to_run = []
            if state["earnings_confidence"] is None:
                to_run.append(("earnings", lambda: EarningsAgent().run(
                    symbol=symbol, thesis=position["thesis"], financials=position.get("financials"),
                    instrument_type=position.get("instrument_type"),
                    forecast_id=forecast_id, macro_state_id=macro_state_id)))
            else:
                earnings_result = self._reconstruct_agent_result(
                    "earnings", state["earnings_model"], state["earnings_output"])
            if state["primary_confidence"] is None:
                to_run.append(("primary_source", lambda: PrimarySourceAgent().run(
                    symbol=symbol, thesis=position["thesis"], financials=position.get("financials"),
                    instrument_type=position.get("instrument_type"),
                    forecast_id=forecast_id, macro_state_id=macro_state_id)))
            else:
                primary_result = self._reconstruct_agent_result(
                    "primary_source", state["primary_model"], state["primary_output"])
            if to_run:
                results = self._run_parallel([fn for _, fn in to_run])
                for (name, _), result in zip(to_run, results):
                    if name == "earnings":
                        earnings_result = result
                    else:
                        primary_result = result
        else:
            logger.info(
                "Skipping Financial/PrimarySource for %s (instrument_type=%r has no "
                "issuer earnings/filings)", symbol, position.get("instrument_type"),
            )

        momentum_r = trend_r = volume_r = tech_judge_result = None
        if tech_context is not None:
            to_run = []
            if state["momentum_signal"] is None:
                to_run.append(("momentum", lambda: MomentumAgent().run(
                    symbol=symbol, tech_context=tech_context,
                    forecast_id=forecast_id, macro_state_id=macro_state_id)))
            else:
                momentum_r = self._reconstruct_agent_result(
                    "momentum", state["momentum_model"], state["momentum_output"])
            if state["trend_signal"] is None:
                to_run.append(("trend", lambda: TrendAgent().run(
                    symbol=symbol, tech_context=tech_context,
                    forecast_id=forecast_id, macro_state_id=macro_state_id)))
            else:
                trend_r = self._reconstruct_agent_result("trend", state["trend_model"], state["trend_output"])
            if state["volume_signal"] is None:
                to_run.append(("volume", lambda: VolumeAgent().run(
                    symbol=symbol, tech_context=tech_context,
                    forecast_id=forecast_id, macro_state_id=macro_state_id)))
            else:
                volume_r = self._reconstruct_agent_result("volume", state["volume_model"], state["volume_output"])
            if to_run:
                results = self._run_parallel([fn for _, fn in to_run])
                for (name, _), result in zip(to_run, results):
                    if name == "momentum":
                        momentum_r = result
                    elif name == "trend":
                        trend_r = result
                    else:
                        volume_r = result

            if state["technical_confidence"] is None:
                tech_judge_result = TechnicalJudgeAgent().run(
                    tech_results=[momentum_r, trend_r, volume_r],
                    forecast_id=forecast_id, macro_state_id=macro_state_id,
                )
            else:
                tech_judge_result = self._reconstruct_agent_result(
                    "tech_judge", state["technical_judge_model"], state["technical_judge_output"])

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
        return symbol_context, risk_result, macro_state_id

    def _load_or_init_stage_c(self, questions: list) -> tuple:
        """Splits questions into (questions, to_rerun). A question already
        carrying a non-NULL final_probability (only possible for a resumed
        forecast_questions row -- a freshly-decomposed question never has this
        key yet) is treated as fully done and its stored per-stage outputs are
        parsed back into the same elicitation_output/review_output/
        confidence_output shape _forecast_question normally produces, so
        AggregationAgent sees a consistent shape either way. Everything else
        goes to to_rerun for the FULL Elicitation->Review->ConfidenceJudge
        chain -- resume never resumes mid-chain within a single question."""
        to_rerun = []
        for question in questions:
            if question.get("final_probability") is not None:
                question["final_probability"] = float(question["final_probability"])
                question["elicitation_output"] = (
                    json.loads(question["elicitation_output"]) if question.get("elicitation_output") else {}
                )
                question["review_output"] = (
                    json.loads(question["review_output"]) if question.get("review_output") else {}
                )
                question["confidence_output"] = (
                    json.loads(question["question_output"]) if question.get("question_output") else {}
                )
            else:
                to_rerun.append(question)
        return questions, to_rerun

    def _reconstruct_agent_result(self, agent_id: str, model_id: Optional[str], output_json: Optional[str]):
        """Stand-in AgentResult for an already-completed Stage-B agent, for
        callers that only read `.output` (symbol_context assembly, RiskJudge's
        macro_summary read, TechnicalJudge's tech_results list). Cost/token/
        duration fields are zeroed -- not re-derivable from the forecasts row
        -- and this never calls log_call(), so no duplicate/fake llm_call_log
        row is created for work that didn't actually happen this run."""
        from forecaster.agents.base import AgentResult

        return AgentResult(
            agent_id=agent_id, model_id=model_id or "", prompt_version_id=0,
            tokens_in=0, tokens_out=0, tokens_cached=0, call_cost_usd=0.0,
            duration_ms=0, output=json.loads(output_json) if output_json else {},
            error=None, response_text=None,
        )

    def _recover_macro_state_id(self, state: dict) -> Optional[int]:
        """Primary path: forecasts.macroq_output already embeds the exact
        root_macro_state_id integer (macroq.py sets it before serializing),
        written once and never overwritten. Fallback only: macro_state.node_id
        carries a per-run UUID suffix that forecasts.macroq_node_id does not,
        so an exact `=` match against it always returns zero rows -- prefix
        match instead."""
        if state["macroq_output"]:
            recovered = json.loads(state["macroq_output"]).get("root_macro_state_id")
            if recovered is not None:
                return recovered
        if state["macroq_node_id"]:
            return find_macro_state_id_by_node_prefix(state["macroq_node_id"])
        return None

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
        """The created_at tiebreak is load-bearing, not cosmetic. forecast_date is
        a DATE stamped date.today() on every run, so every same-day re-run (which
        is exactly what --force produces) ties on it. Ordering by forecast_date
        alone left the winner among tied rows unspecified, and Postgres resolved
        it by physical heap order — which, since rows are appended in insertion
        order, reliably returned the OLDEST run of the day rather than the newest.
        That silently gated triage on a superseded score (observed live: NOVT read
        id=27 adjusted_score=-0.0474 and rejected, while the current row id=28 held
        +0.3580 and should have proceeded). The old behaviour wasn't even stably
        wrong: heap order shifts on UPDATE, VACUUM FULL/CLUSTER, or the plan
        flipping to an index scan, so it could silently start returning a
        different tied row with no code change.
        """
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT adjusted_score
                FROM forecasts
                WHERE symbol = %s AND adjusted_score IS NOT NULL
                ORDER BY forecast_date DESC, created_at DESC
                LIMIT 1
                """,
                (symbol,),
            )
            row = cur.fetchone()
            return float(row[0]) if row else None

    # Matches a leading High/Medium/Low rating word in profile_rationale free
    # text (e.g. "Medium confidence. Narrative sections all populated...") --
    # used only to detect a stale sync-layer regression below, never to
    # silently substitute a value the pipeline should be reading directly
    # from profile_confidence_rating.
    _RATIONALE_RATING_RE = re.compile(r"^(High|Medium|Low)\b", re.IGNORECASE)

    def _get_position_context(self, symbol: str) -> dict:
        cols = [
            "investment_thesis", "risks", "business", "competitive_landscape", "financials",
            "hold_period", "hold_period_rationale", "name", "label", "type", "asymmetric_rating",
            "risk_level", "risk_level_rationale", "tags", "source_name", "source_link",
            "profile_change_log", "profile_confidence_rating", "profile_rationale",
            "profile_model", "thesis_test_date", "thesis_list", "thesis_list_rationale",
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
        if isinstance(position.get("drawdown_threshold"), Decimal):
            position["drawdown_threshold"] = float(position["drawdown_threshold"])
        if isinstance(position.get("thesis_test_date"), date):
            position["thesis_test_date"] = position["thesis_test_date"].isoformat()
        position["thesis"] = position.pop("investment_thesis") or ""
        position["instrument_type"] = position.pop("type") or None
        position["profile_confidence"] = position.pop("profile_confidence_rating") or None
        # Regression guard: profile_confidence_rating (VARCHAR, synced from the
        # Inventory sheet's Profile Confidence column) should never be null
        # while profile_rationale plainly names a rating -- that shape is
        # exactly what excel_sync's decimal-coercion bug produced (see
        # migrations/007_profile_confidence_rating.sql in
        # investment-portfolio-manager). Logged loudly rather than silently
        # backfilled from the rationale, so a sync-layer regression is
        # visible immediately instead of masked a second time.
        if not position["profile_confidence"]:
            rationale = position.get("profile_rationale") or ""
            match = self._RATIONALE_RATING_RE.match(rationale.strip())
            if match:
                logger.warning(
                    "%s: profile_confidence_rating is empty but profile_rationale "
                    "starts with %r -- the Excel sync likely dropped this position's "
                    "rating again. Check excel_sync.py's coercion for "
                    "profile_confidence_rating.",
                    symbol, match.group(1),
                )
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

    def _question_insert_kwargs(self, question: dict) -> dict:
        """kwargs for insert_forecast_question() from a raw decomposition-output
        question dict (either freshly produced by QuestionDefinitionAgent or
        parsed back out of a stored forecasts.question_def_output blob during
        a Stage-A repair -- same shape either way)."""
        return dict(
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
