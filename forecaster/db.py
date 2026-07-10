import os
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_HOST = os.getenv('DB_HOST', 'localhost')
_PORT = int(os.getenv('DB_PORT', '5432'))
_NAME = os.getenv('DB_NAME', 'investment_forecaster')
_USER = os.getenv('DB_USER', 'postgres')
_PASSWORD = os.getenv('DB_PASSWORD', '')
_PORTFOLIO_NAME = os.getenv('PORTFOLIO_DB_NAME', 'investment_portfolio')


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
