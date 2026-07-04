#!/usr/bin/env python3
import glob
import os
import re
import sys

import pyodbc
from dotenv import load_dotenv

load_dotenv()


def _get_conn() -> pyodbc.Connection:
    server = os.getenv('DB_SERVER', r'James-desktop\sqlexpress')
    database = os.getenv('DB_NAME', 'DMS')
    driver = os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')
    return pyodbc.connect(
        f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;'
    )


def run_migrations() -> None:
    migrations_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
    sql_files = sorted(glob.glob(os.path.join(migrations_dir, '*.sql')))
    if not sql_files:
        print('No migration files found.')
        return

    conn = _get_conn()
    cursor = conn.cursor()

    for filepath in sql_files:
        print(f'Applying {os.path.basename(filepath)} ...')
        with open(filepath, encoding='utf-8') as fh:
            sql = fh.read()

        batches = re.split(r'^\s*GO\s*$', sql, flags=re.MULTILINE)
        for batch in batches:
            clean = re.sub(r'--[^\n]*', '', batch).strip()
            if clean:
                cursor.execute(batch)
        conn.commit()
        print('  ok')

    cursor.close()
    conn.close()
    print('All migrations complete.')


if __name__ == '__main__':
    try:
        run_migrations()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
