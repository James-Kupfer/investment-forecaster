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
