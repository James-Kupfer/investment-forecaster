import contextlib
from unittest.mock import patch


def test_db_connection():
    from forecaster.db import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1')
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_schema_tables_exist():
    from forecaster.db import get_connection
    expected = {
        'prompt_registry', 'macro_state',
        'position_catalysts', 'position_sources', 'forecasts',
        'llm_call_log', 'agent_weights', 'sync_log',
    }
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    actual = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert expected.issubset(actual), f'Missing tables: {expected - actual}'


def test_portfolio_db_connection():
    from forecaster.db import get_portfolio_connection
    conn = get_portfolio_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1')
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_portfolio_tables_exist():
    from forecaster.db import get_portfolio_connection
    expected = {'positions', 'sync_log'}
    conn = get_portfolio_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    actual = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert expected.issubset(actual), f'Missing portfolio tables: {expected - actual}'


# ---------------------------------------------------------------------------
# ForecastPipeline._get_prior_adjusted_score — the triage gate's only input
#
# These live here rather than in test_pipeline.py because the behaviour under
# test is ORDER BY resolution, which only a real Postgres can evaluate. A mocked
# cursor would replay whatever order the mock was handed and prove nothing about
# the query — which is precisely how the tiebreak bug survived: the gate that
# decides whether to spend a full pipeline run on a symbol had no test at all.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _pipeline_on_rolled_back_txn():
    """Yield (cursor, ForecastPipeline) with forecaster.pipeline.db_cursor patched
    onto a single uncommitted transaction against the live DB.

    get_connection() leaves autocommit off (psycopg2's default), so rows inserted
    here are never visible to another connection and are discarded even if an
    assertion raises — the real forecasts table is never written to.
    """
    from forecaster.db import get_connection
    from forecaster.pipeline import ForecastPipeline

    conn = get_connection()
    try:
        cur = conn.cursor()

        @contextlib.contextmanager
        def _fake_db_cursor():
            yield cur  # no commit — the outer finally always rolls back

        with patch('forecaster.pipeline.db_cursor', _fake_db_cursor):
            yield cur, ForecastPipeline()
    finally:
        conn.rollback()
        conn.close()


def test_get_prior_adjusted_score_prefers_newest_same_day_run():
    """forecast_date is a DATE stamped date.today() on every run, so same-day
    re-runs (exactly what --force produces) all tie on it. Ordering by
    forecast_date alone left the winner among ties unspecified; Postgres resolved
    it by physical heap order, which — rows being appended in insertion order —
    reliably returned the OLDEST run of the day. Observed live on NOVT: triage
    read a superseded -0.0474 and rejected the symbol while the current row held
    +0.3580 and should have proceeded.
    """
    symbol = '__TEST_NEWEST__'
    with _pipeline_on_rolled_back_txn() as (cur, pipeline):
        # Inserted oldest-first so heap order matches insertion order: the exact
        # shape that made the pre-fix query return 0.11 instead of 0.99.
        cur.execute(
            """
            INSERT INTO forecasts (symbol, forecast_date, resolution_date, adjusted_score, created_at)
            VALUES (%s, DATE '2026-01-02', DATE '2026-04-02', 0.1100, TIMESTAMP '2026-01-02 09:00:00'),
                   (%s, DATE '2026-01-02', DATE '2026-04-02', 0.2200, TIMESTAMP '2026-01-02 10:00:00'),
                   (%s, DATE '2026-01-02', DATE '2026-04-02', 0.9900, TIMESTAMP '2026-01-02 11:00:00')
            """,
            (symbol, symbol, symbol),
        )
        assert pipeline._get_prior_adjusted_score(symbol) == 0.99


def test_get_prior_adjusted_score_keeps_forecast_date_as_primary_sort():
    """created_at is only a tiebreak within a date, not the primary key: a later
    business date must win even when an earlier-dated row was inserted more
    recently (backfill / backdated re-run). Pins the choice of
    'forecast_date DESC, created_at DESC' over a bare 'created_at DESC'.
    """
    symbol = '__TEST_DATE__'
    with _pipeline_on_rolled_back_txn() as (cur, pipeline):
        cur.execute(
            """
            INSERT INTO forecasts (symbol, forecast_date, resolution_date, adjusted_score, created_at)
            VALUES (%s, DATE '2026-01-09', DATE '2026-04-09', 0.7700, TIMESTAMP '2026-01-09 09:00:00'),
                   (%s, DATE '2026-01-02', DATE '2026-04-02', 0.1100, TIMESTAMP '2026-01-20 23:00:00')
            """,
            (symbol, symbol),
        )
        assert pipeline._get_prior_adjusted_score(symbol) == 0.77


def test_get_prior_adjusted_score_ignores_unscored_rows():
    """A newer partial row (pipeline died before aggregation, adjusted_score NULL)
    must not mask the last actually-scored run."""
    symbol = '__TEST_NULL__'
    with _pipeline_on_rolled_back_txn() as (cur, pipeline):
        cur.execute(
            """
            INSERT INTO forecasts (symbol, forecast_date, resolution_date, adjusted_score, created_at)
            VALUES (%s, DATE '2026-01-02', DATE '2026-04-02', 0.4200, TIMESTAMP '2026-01-02 09:00:00'),
                   (%s, DATE '2026-01-02', DATE '2026-04-02', NULL,   TIMESTAMP '2026-01-02 11:00:00')
            """,
            (symbol, symbol),
        )
        assert pipeline._get_prior_adjusted_score(symbol) == 0.42


def test_get_prior_adjusted_score_returns_none_for_unknown_symbol():
    """No prior row => None => TriageAgent treats it as a first run and proceeds."""
    with _pipeline_on_rolled_back_txn() as (_cur, pipeline):
        assert pipeline._get_prior_adjusted_score('__TEST_NONE__') is None
