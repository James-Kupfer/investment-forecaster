#!/usr/bin/env python
"""Run all SQL migrations in migrations/ against PostgreSQL.

Idempotent: every migration uses CREATE TABLE IF NOT EXISTS / DO $$ blocks.
Splits on ';' and executes each statement under autocommit.
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_HOST = os.getenv('DB_HOST', 'localhost')
_PORT = int(os.getenv('DB_PORT', '5432'))
_NAME = os.getenv('DB_NAME', 'investment_forecaster')
_USER = os.getenv('DB_USER', 'postgres')
_PASSWORD = os.getenv('DB_PASSWORD', '')

MIGRATIONS_DIR = Path(__file__).parent.parent / 'migrations'


def run_migrations() -> None:
    conn = psycopg2.connect(host=_HOST, port=_PORT, dbname=_NAME, user=_USER, password=_PASSWORD)
    conn.autocommit = True
    cursor = conn.cursor()

    mig_files = sorted(MIGRATIONS_DIR.glob('*.sql'))
    if not mig_files:
        print('No migration files found in', MIGRATIONS_DIR)
        return

    for mf in mig_files:
        sql = mf.read_text(encoding='utf-8').strip()
        if not sql or sql.startswith('--'):
            print(f'  skip  {mf.name} (no-op)')
            continue
        print(f'Applying {mf.name}...')
        for stmt in (s.strip() for s in sql.split(';') if s.strip()):
            cursor.execute(stmt)
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
