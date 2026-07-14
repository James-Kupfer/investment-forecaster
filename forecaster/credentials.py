"""Loads credentials directly from the shared C:\\Users\\james\\GitHub\\Secrets
folder — the single source of truth used across all of James's repos. No .env
file is used for secrets; this avoids each repo carrying its own duplicated
copy of the same Postgres password / Anthropic API key.

Loaded via importlib with an explicit file path (not sys.path + `import
anthropic`) because Secrets\\Anthropic.py would otherwise shadow the real
`anthropic` SDK package for every other module in the process.
"""
import importlib.util
import os

_SECRETS_DIR = r"C:\Users\james\GitHub\Secrets"


def _load_module(filename: str, module_name: str):
    path = os.path.join(_SECRETS_DIR, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load() -> None:
    pg = _load_module("postgres.py", "_secrets_postgres")
    os.environ.setdefault("DB_HOST", pg.dsn)
    os.environ.setdefault("DB_USER", pg.postgres_user)
    os.environ.setdefault("DB_PASSWORD", pg.postgres_password)

    anth = _load_module("Anthropic.py", "_secrets_anthropic")
    os.environ.setdefault("ANTHROPIC_API_KEY", anth.ANTHROPIC_API_KEY)

    sec = _load_module("SEC.py", "_secrets_sec")
    os.environ.setdefault("SEC_EDGAR_USER_AGENT", sec.SEC_EDGAR_USER_AGENT)


_load()
