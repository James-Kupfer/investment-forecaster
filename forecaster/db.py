import os
from contextlib import contextmanager
import pyodbc
from dotenv import load_dotenv

load_dotenv()

_SERVER = os.getenv('DB_SERVER', r'James-desktop\sqlexpress')
_DATABASE = os.getenv('DB_NAME', 'DMS')
_DRIVER = os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')


def get_connection() -> pyodbc.Connection:
    return pyodbc.connect(
        f'DRIVER={{{_DRIVER}}};SERVER={_SERVER};DATABASE={_DATABASE};Trusted_Connection=yes;'
    )


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


def update_forecast_columns(forecast_id: int, **kwargs) -> None:
    """UPDATE forecasts SET col=val, ... WHERE id=forecast_id."""
    if not kwargs:
        return
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [forecast_id]
    with db_cursor() as cur:
        cur.execute(f"UPDATE forecasts SET {cols} WHERE id = ?", tuple(values))
