import os
from contextlib import contextmanager

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
