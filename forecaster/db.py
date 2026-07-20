import os
from contextlib import contextmanager
from datetime import date
from typing import Optional

import psycopg2

import forecaster.credentials  # noqa: F401 (loads DB_*/ANTHROPIC_API_KEY into os.environ)
from forecaster.config import DATABASE

# host/user/password are secrets (from the Secrets folder via credentials.py)
# -- never sourced from config.toml, and no Python-literal fallback here
# either (DB_HOST has none for the same reason -- see credentials.py; USER/
# PASSWORD have no safe universal default so an empty password is the only
# sane fallback). port/name/portfolio_db_name DO have safe universal
# defaults, but those live in config.example.toml, not duplicated here as
# Python literals -- see forecaster/config.py's DATABASE merge.
_HOST = os.getenv('DB_HOST', 'localhost')
_PORT = int(os.getenv('DB_PORT', DATABASE['port']))
_NAME = os.getenv('DB_NAME', DATABASE['name'])
_USER = os.getenv('DB_USER', 'postgres')
_PASSWORD = os.getenv('DB_PASSWORD', '')
_PORTFOLIO_NAME = os.getenv('PORTFOLIO_DB_NAME', DATABASE['portfolio_db_name'])


def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(host=_HOST, port=_PORT, dbname=_NAME, user=_USER, password=_PASSWORD)


def get_portfolio_connection() -> psycopg2.extensions.connection:
    """Connection to investment_portfolio — positions are owned by portfolio-manager."""
    return psycopg2.connect(host=_HOST, port=_PORT, dbname=_PORTFOLIO_NAME, user=_USER, password=_PASSWORD)


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def portfolio_db_cursor():
    """Cursor for investment_portfolio — read positions from the portfolio-manager DB."""
    conn = get_portfolio_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_forecast_columns(forecast_id: int, **kwargs) -> None:
    """UPDATE forecasts SET col=val, ... WHERE id=forecast_id."""
    if not kwargs:
        return
    cols = ", ".join(f"{k} = %s" for k in kwargs)
    values = list(kwargs.values()) + [forecast_id]
    with db_cursor() as cur:
        cur.execute(f"UPDATE forecasts SET {cols} WHERE id = %s", tuple(values))


def insert_forecast_question(forecast_id: int, **kwargs) -> int:
    """INSERT INTO forecast_questions (forecast_id, col, ...) VALUES (...) RETURNING id."""
    cols = ["forecast_id"] + list(kwargs.keys())
    values = [forecast_id] + list(kwargs.values())
    placeholders = ", ".join(["%s"] * len(cols))
    with db_cursor() as cur:
        cur.execute(
            f"INSERT INTO forecast_questions ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            tuple(values),
        )
        row = cur.fetchone()
    return int(row[0])


def update_forecast_question_columns(question_id: int, **kwargs) -> None:
    """UPDATE forecast_questions SET col=val, ... WHERE id=question_id."""
    if not kwargs:
        return
    cols = ", ".join(f"{k} = %s" for k in kwargs)
    values = list(kwargs.values()) + [question_id]
    with db_cursor() as cur:
        cur.execute(f"UPDATE forecast_questions SET {cols} WHERE id = %s", tuple(values))


def _rows_as_dicts(cur) -> list[dict]:
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_forecast(forecast_id: int) -> Optional[dict]:
    """Full forecasts row as a {column: value} dict, or None if it doesn't exist.
    Used by ForecastPipeline.resume() to read every stage's sentinel column at once."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM forecasts WHERE id = %s", (forecast_id,))
        rows = _rows_as_dicts(cur)
    return rows[0] if rows else None


def get_forecast_questions(forecast_id: int) -> list[dict]:
    """All forecast_questions rows for forecast_id, oldest first -- matches the
    original insertion order from ForecastPipeline's Stage-A insert loop, which
    is a plain sequential `for` (one INSERT per question)."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM forecast_questions WHERE forecast_id = %s ORDER BY id ASC",
            (forecast_id,),
        )
        return _rows_as_dicts(cur)


def find_incomplete_forecasts(forecast_date: date, symbols: Optional[list] = None) -> list[dict]:
    """The latest (by created_at) forecasts row per symbol for forecast_date
    whose recommendation is still NULL -- i.e. never reached a real Stage-D
    outcome, whether that's because the pipeline hard-crashed mid-run or
    because it silently degraded all the way through (BaseAgent.call()
    swallows LLM/network failures rather than raising, so a full-outage run
    can finish "successfully" with every stage empty -- see
    ForecastPipeline.resume()). This is the DB-driven way to discover which
    symbols in a batch run actually need reprocessing; a batch run's console
    "Failed symbols" log only catches the hard-crash case and misses the
    silent-degradation one entirely.

    created_at DESC is the same same-day tie-break already load-bearing in
    ForecastPipeline._get_prior_adjusted_score -- forecast_date alone ties on
    every same-day re-run/resume attempt, and ordering by created_at DESC is
    what correctly picks the newest attempt rather than an arbitrary one.
    """
    query = (
        "SELECT DISTINCT ON (symbol) * FROM forecasts "
        "WHERE forecast_date = %s AND recommendation IS NULL"
    )
    params: list = [forecast_date.isoformat()]
    if symbols:
        query += " AND symbol = ANY(%s)"
        params.append(list(symbols))
    query += " ORDER BY symbol, created_at DESC"
    with db_cursor() as cur:
        cur.execute(query, tuple(params))
        return _rows_as_dicts(cur)


def find_macro_state_id_by_node_prefix(node_id_prefix: str) -> Optional[int]:
    """Fallback only -- macro_state.node_id has a per-run UUID suffix appended
    (see macroq.py's _persist_tree) that forecasts.macroq_node_id doesn't carry,
    so this can only ever prefix-match, never exact-match. The primary recovery
    path (forecasts.macroq_output already embeds the exact root_macro_state_id
    integer) doesn't need this at all; use it only if that JSON is somehow
    missing/malformed."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT id FROM macro_state WHERE node_id LIKE %s ORDER BY id DESC LIMIT 1",
            (f"{node_id_prefix}_%",),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None
