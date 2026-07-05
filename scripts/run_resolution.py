"""
Resolution job.

For every unresolved forecast past its resolution_date:
1. Fetches closing price at resolution_date via yfinance
2. Determines invq1 (upside) and invq2 (downside) binary outcomes
3. Computes Brier scores: (probability - outcome)^2
4. Updates forecasts row and agent_weights rolling accuracy
"""
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _price_on_date_approx(symbol: str, target_date: date, days_back: int = 5) -> Optional[float]:
    """Fetch closing price within `days_back` of target_date."""
    import yfinance as yf
    from datetime import timedelta
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


def _update_agent_weight(
    cur,
    agent_id: str,
    question_type: str,
    model_id: str,
    brier: float,
) -> None:
    cur.execute(
        """
        SELECT rolling_accuracy, sample_size
        FROM agent_weights
        WHERE agent_id = ? AND question_type = ? AND model_id = ?
        """,
        agent_id, question_type, model_id,
    )
    row = cur.fetchone()
    accuracy = 1.0 - brier
    if row:
        n = row[1] + 1
        new_rolling = ((row[0] or 0.0) * row[1] + accuracy) / n
        cur.execute(
            """
            UPDATE agent_weights
            SET rolling_accuracy = ?, sample_size = ?, last_updated = GETDATE()
            WHERE agent_id = ? AND question_type = ? AND model_id = ?
            """,
            new_rolling, n, agent_id, question_type, model_id,
        )
    else:
        cur.execute(
            """
            INSERT INTO agent_weights
                (agent_id, question_type, model_id, rolling_accuracy, sample_size)
            VALUES (?, ?, ?, ?, 1)
            """,
            agent_id, question_type, model_id, accuracy,
        )


def resolve_forecast(row: tuple) -> None:
    from forecaster.db import db_cursor

    (
        forecast_id, symbol, resolution_date_str, forecast_date_str,
        invq1_p, invq2_p, invq1_model, invq2_model,
        upside_threshold, drawdown_threshold,
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
            SET resolved = 1,
                resolved_outcome = ?,
                brier_q1 = ?,
                brier_q2 = ?
            WHERE id = ?
            """,
            resolved_outcome, brier_q1, brier_q2, forecast_id,
        )
        if brier_q1 is not None and invq1_model:
            _update_agent_weight(cur, "aggregation", "invq1", invq1_model, brier_q1)
        if brier_q2 is not None and invq2_model:
            _update_agent_weight(cur, "aggregation", "invq2", invq2_model, brier_q2)

    logger.info(
        "forecast_id=%d %s resolved: pct_change=%.2f%% q1=%d(b=%.4f) q2=%d(b=%.4f)",
        forecast_id, symbol, pct_change * 100,
        outcome_q1, brier_q1 or 0,
        outcome_q2, brier_q2 or 0,
    )


def main() -> None:
    from forecaster.db import db_cursor

    today = date.today().isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                f.id, f.symbol, f.resolution_date, f.forecast_date,
                f.invq1_p, f.invq2_p, f.invq1_model, f.invq2_model,
                p.upside_threshold, p.drawdown_threshold
            FROM forecasts f
            JOIN positions p ON f.symbol = p.symbol
            WHERE f.resolved = 0
              AND f.resolution_date <= ?
              AND (f.invq1_p IS NOT NULL OR f.invq2_p IS NOT NULL)
            ORDER BY f.resolution_date
            """,
            today,
        )
        rows = cur.fetchall()

    if not rows:
        logger.info("No unresolved forecasts past resolution_date")
        return

    logger.info("Resolving %d forecasts", len(rows))
    for row in rows:
        try:
            resolve_forecast(tuple(row))
        except Exception as exc:
            logger.error("forecast_id=%s failed: %s", row[0], exc)


if __name__ == "__main__":
    main()
