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
