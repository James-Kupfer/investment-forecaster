#!/usr/bin/env python
"""Run all SQL migrations in migrations/ against SQL Server.

Idempotent: every migration uses IF NOT EXISTS / IF OBJECT_ID IS NULL guards.
Splits on GO (line-level, case-insensitive) and executes each batch separately
under autocommit so CREATE DATABASE runs outside any transaction.
"""
import os
import re
import sys
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

load_dotenv()

_SERVER = os.getenv('DB_SERVER', r'James-desktop\sqlexpress')
_DRIVER = os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')
MIGRATIONS_DIR = Path(__file__).parent.parent / 'migrations'


def split_on_go(sql: str) -> list[str]:
    batches = re.split(r'^\s*GO\s*$', sql, flags=re.IGNORECASE | re.MULTILINE)
    return [b.strip() for b in batches if b.strip()]


def run_migrations() -> None:
    conn = pyodbc.connect(
        f'DRIVER={{{_DRIVER}}};SERVER={_SERVER};DATABASE=master;Trusted_Connection=yes;',
        autocommit=True,
    )
    cursor = conn.cursor()

    mig_files = sorted(MIGRATIONS_DIR.glob('*.sql'))
    if not mig_files:
        print('No migration files found in', MIGRATIONS_DIR)
        return

    for mf in mig_files:
        print(f'Applying {mf.name}...')
        sql = mf.read_text(encoding='utf-8')
        for batch in split_on_go(sql):
            cursor.execute(batch)
        print(f'  OK')

    cursor.close()
    conn.close()
    print('Migrations complete.')


if __name__ == '__main__':
    try:
        run_migrations()
    except Exception as exc:
        print(f'Migration failed: {exc}', file=sys.stderr)
        sys.exit(1)
