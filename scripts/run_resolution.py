"""
Resolution job.

Two independent passes (see
C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md):

1. Legacy v1 forecasts (single-question model, invq1_p/invq2_p): unchanged
   behavior, retained so historical unresolved rows from before the
   decomposition pipeline still get scored.
2. v2 forecast_questions (decomposition model): for every unresolved
   sub-question past its resolution_date —
     - price-sourced: best-effort auto-resolve via yfinance, extracting a
       $threshold and direction from the free-text resolution_criteria.
     - filing/manual-sourced: CANNOT be auto-resolved. Event-based questions
       forecast more accurately than price bets but require reading an actual
       filing/press release to resolve — this is an accepted, documented
       limitation, not a bug. These are surfaced in a needs-resolution report
       for manual or LLM-assisted marking, not silently skipped or guessed.

Both passes compute Brier scores and update agent_weights rolling accuracy;
the v2 pass keys accuracy by question_type (catalyst|risk) so calibration
accrues separately for each, per confidence_judge model.

Note: positions thresholds/symbols are read from the portfolio database
separately; PostgreSQL does not support cross-database queries.
"""
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _price_on_date_approx(symbol: str, target_date: date, days_back: int = 5) -> Optional[float]:
    """Fetch closing price within `days_back` of target_date."""
    import yfinance as yf
    start = (target_date - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    hist = yf.Ticker(symbol).history(start=start, end=end)
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


def _brier(probability: Optional[float], outcome: int) -> Optional[float]:
    if probability is None:
        return None
    return round((probability - outcome) ** 2, 6)


def _update_agent_weight(cur, agent_id: str, question_type: str, model_id: str, brier: float) -> None:
    cur.execute(
        """
        SELECT rolling_accuracy, sample_size
        FROM agent_weights
        WHERE agent_id = %s AND question_type = %s AND model_id = %s
        """,
        (agent_id, question_type, model_id),
    )
    row = cur.fetchone()
    accuracy = 1.0 - brier
    if row:
        n = row[1] + 1
        new_rolling = ((row[0] or 0.0) * row[1] + accuracy) / n
        cur.execute(
            """
            UPDATE agent_weights
            SET rolling_accuracy = %s, sample_size = %s, last_updated = NOW()
            WHERE agent_id = %s AND question_type = %s AND model_id = %s
            """,
            (new_rolling, n, agent_id, question_type, model_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO agent_weights
                (agent_id, question_type, model_id, rolling_accuracy, sample_size)
            VALUES (%s, %s, %s, %s, 1)
            """,
            (agent_id, question_type, model_id, accuracy),
        )


# ----------------------------------------------------------------------
# Pass 1 — legacy v1 single-question forecasts (retained for historical rows)
# ----------------------------------------------------------------------

def resolve_legacy_forecast(row: tuple, upside_threshold: float, drawdown_threshold: float) -> None:
    from forecaster.db import db_cursor

    (
        forecast_id, symbol, resolution_date_str, forecast_date_str,
        invq1_p, invq2_p, invq1_model, invq2_model,
    ) = row

    resolution_date = date.fromisoformat(str(resolution_date_str))
    forecast_date = date.fromisoformat(str(forecast_date_str))

    price_forecast = _price_on_date_approx(symbol, forecast_date)
    price_resolved = _price_on_date_approx(symbol, resolution_date)

    if price_forecast is None or price_resolved is None or price_forecast == 0:
        logger.warning(
            "forecast_id=%d: could not fetch prices for %s — skipping",
            forecast_id, symbol,
        )
        return

    pct_change = (price_resolved - price_forecast) / price_forecast

    outcome_q1 = 1 if pct_change >= float(upside_threshold or 0.20) else 0
    outcome_q2 = 1 if pct_change <= -float(drawdown_threshold or 0.20) else 0

    brier_q1 = _brier(invq1_p, outcome_q1)
    brier_q2 = _brier(invq2_p, outcome_q2)

    resolved_outcome = (
        f"pct_change={pct_change:.4f} "
        f"outcome_q1={outcome_q1} outcome_q2={outcome_q2}"
    )

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE forecasts
            SET resolved = TRUE,
                resolved_outcome = %s,
                brier_q1 = %s,
                brier_q2 = %s
            WHERE id = %s
            """,
            (resolved_outcome, brier_q1, brier_q2, forecast_id),
        )
        if brier_q1 is not None and invq1_model:
            _update_agent_weight(cur, "aggregation", "invq1", invq1_model, brier_q1)
        if brier_q2 is not None and invq2_model:
            _update_agent_weight(cur, "aggregation", "invq2", invq2_model, brier_q2)

    logger.info(
        "forecast_id=%d %s resolved (legacy v1): pct_change=%.2f%% q1=%d(b=%.4f) q2=%d(b=%.4f)",
        forecast_id, symbol, pct_change * 100,
        outcome_q1, brier_q1 or 0,
        outcome_q2, brier_q2 or 0,
    )


def resolve_legacy_pass() -> None:
    from forecaster.db import db_cursor, portfolio_db_cursor

    with portfolio_db_cursor() as cur:
        cur.execute("SELECT symbol, upside_threshold, drawdown_threshold FROM positions")
        thresholds = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    today = date.today().isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                id, symbol, resolution_date, forecast_date,
                invq1_p, invq2_p, invq1_model, invq2_model
            FROM forecasts
            WHERE resolved = FALSE
              AND resolution_date <= %s
              AND (invq1_p IS NOT NULL OR invq2_p IS NOT NULL)
            ORDER BY resolution_date
            """,
            (today,),
        )
        rows = cur.fetchall()

    if not rows:
        logger.info("No unresolved legacy v1 forecasts past resolution_date")
        return

    logger.info("Resolving %d legacy v1 forecasts", len(rows))
    for row in rows:
        symbol = row[1]
        upside, drawdown = thresholds.get(symbol, (0.20, 0.20))
        try:
            resolve_legacy_forecast(tuple(row), upside, drawdown)
        except Exception as exc:
            logger.error("forecast_id=%s failed: %s", row[0], exc)


# ----------------------------------------------------------------------
# Pass 2 — v2 decomposed forecast_questions
# ----------------------------------------------------------------------

def _extract_price_threshold(resolution_criteria: str) -> Optional[tuple]:
    """Best-effort extraction of a $threshold and direction from free-text
    resolution_criteria. Returns None when no clear numeric threshold and
    direction can be extracted — those route to the needs-resolution report
    rather than a guessed outcome."""
    if not resolution_criteria:
        return None
    match = re.search(r'\$([\d,]+\.?\d*)', resolution_criteria)
    if not match:
        return None
    threshold = float(match.group(1).replace(',', ''))
    if re.search(r'\b(above|exceed|exceeds|over)\b', resolution_criteria, re.IGNORECASE):
        direction = 'above'
    elif re.search(r'\b(below|under)\b', resolution_criteria, re.IGNORECASE):
        direction = 'below'
    else:
        return None
    return threshold, direction


def resolve_price_question(
    question_id: int, symbol: str, resolution_date_str: str, resolution_criteria: str,
    question_type: str, final_probability: Optional[float], model_id: Optional[str],
) -> bool:
    """Attempt to auto-resolve a price-sourced sub-question. Returns True if resolved."""
    from forecaster.db import db_cursor

    resolution_date = date.fromisoformat(str(resolution_date_str))
    threshold_info = _extract_price_threshold(resolution_criteria)
    if threshold_info is None:
        return False

    threshold, direction = threshold_info
    price = _price_on_date_approx(symbol, resolution_date)
    if price is None:
        logger.warning("question_id=%d: could not fetch price for %s — skipping", question_id, symbol)
        return False

    outcome = 1 if (price > threshold if direction == "above" else price < threshold) else 0
    brier = _brier(final_probability, outcome)
    resolved_outcome = f"price={price:.2f} threshold={threshold:.2f} direction={direction} outcome={outcome}"

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE forecast_questions
            SET resolved = TRUE, resolved_outcome = %s, brier = %s
            WHERE id = %s
            """,
            (resolved_outcome, brier, question_id),
        )
        if brier is not None and model_id:
            _update_agent_weight(cur, "confidence_judge", question_type, model_id, brier)

    logger.info(
        "question_id=%d %s resolved (price): %s brier=%.4f",
        question_id, symbol, resolved_outcome, brier or 0,
    )
    return True


def resolve_forecast_questions_pass() -> None:
    from forecaster.db import db_cursor

    today = date.today().isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT fq.id, fq.forecast_id, fq.question_type, fq.question_text,
                   fq.resolution_criteria, fq.resolution_date, fq.resolution_source,
                   fq.final_probability, fq.model_id, f.symbol
            FROM forecast_questions fq
            JOIN forecasts f ON f.id = fq.forecast_id
            WHERE fq.resolved = FALSE
              AND fq.resolution_date <= %s
              AND fq.final_probability IS NOT NULL
            ORDER BY fq.resolution_date
            """,
            (today,),
        )
        rows = cur.fetchall()

    if not rows:
        logger.info("No unresolved forecast_questions past resolution_date")
        return

    auto_resolved = 0
    needs_manual_resolution = []
    for row in rows:
        (question_id, forecast_id, question_type, question_text, resolution_criteria,
         resolution_date_str, resolution_source, final_probability, model_id, symbol) = row

        resolved = False
        if resolution_source == "price":
            try:
                resolved = resolve_price_question(
                    question_id, symbol, resolution_date_str, resolution_criteria,
                    question_type, final_probability, model_id,
                )
            except Exception as exc:
                logger.error("question_id=%s failed: %s", question_id, exc)

        if resolved:
            auto_resolved += 1
        else:
            needs_manual_resolution.append((question_id, symbol, question_type, resolution_source, question_text))

    logger.info("Auto-resolved %d price-sourced sub-questions", auto_resolved)
    if needs_manual_resolution:
        logger.info(
            "%d sub-questions need manual/filing-based resolution (see CLAUDE.md "
            "for why this isn't automated):",
            len(needs_manual_resolution),
        )
        for question_id, symbol, question_type, resolution_source, question_text in needs_manual_resolution:
            logger.info(
                "  [%s] question_id=%d (%s/%s): %s",
                symbol, question_id, question_type, resolution_source, question_text,
            )


def main() -> None:
    resolve_legacy_pass()
    resolve_forecast_questions_pass()


if __name__ == "__main__":
    main()
