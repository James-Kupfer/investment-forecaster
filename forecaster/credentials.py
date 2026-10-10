"""Loads credentials directly from the shared Secrets folder(s) -- the single
source of truth used across all of the owner's repos. No .env file is used for
secrets; this avoids each repo carrying its own duplicated copy of the same
Postgres password / Anthropic API key.

forecaster.config.SECRETS_DIRS lists candidate directories (sourced from
config.toml's [secrets] override, or the FORECASTER_SECRETS_DIR env var --
see forecaster/config.py), searched in order: some environments (e.g. a
self-hosted CI runner on a different Windows profile) carry differently
-named secret files (api_key.py/sec_id.py, SEC_USER_AGENT) instead of the
interactive account's (inv_forecaster_key.py/SEC.py, SEC_EDGAR_USER_AGENT) -- both
names are tried in every candidate directory. The first entry of each list is
the LLM_Config layout (shared/<service>/..., projects/<repo>/...); the bare
names are the legacy flat-folder layout.

Loaded via importlib with an explicit file path (not sys.path + `import
anthropic`) because Secrets\\Anthropic.py would otherwise shadow the real
`anthropic` SDK package for every other module in the process.
"""
import importlib.util
import os

from forecaster.config import SECRETS_DIRS, SecretsNotFoundError

__all__ = ["SecretsNotFoundError"]  # re-exported for convenience; canonical home is forecaster.config


def _find_module(filenames: list, module_name: str):
    """Search each candidate secrets directory, in order, for the first of
    *filenames* that exists."""
    if not SECRETS_DIRS:
        raise SecretsNotFoundError(
            "No secrets directory configured. Copy config.example.toml to "
            "config.toml and set [secrets] override to your Secrets folder, "
            "or set the FORECASTER_SECRETS_DIR environment variable. See "
            "README.md's \"Credentials\" section."
        )
    for secrets_dir in SECRETS_DIRS:
        for filename in filenames:
            path = os.path.join(secrets_dir, filename)
            if os.path.isfile(path):
                spec = importlib.util.spec_from_file_location(module_name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    raise SecretsNotFoundError(
        f"None of {filenames} found in any of {SECRETS_DIRS}. Check "
        f"config.toml's [secrets] override (or FORECASTER_SECRETS_DIR) "
        f"points at the folder that actually contains them."
    )


def _load() -> None:
    pg = _find_module(["shared/postgres/role_investment_forecaster.py", "postgres.py"], "_secrets_postgres")
    os.environ.setdefault("DB_HOST", pg.dsn)
    os.environ.setdefault("DB_USER", pg.postgres_user)
    os.environ.setdefault("DB_PASSWORD", pg.postgres_password)

    # First entry is the LLM_Config layout; inv_forecaster_key.py is this project's own
    # key in the flat layout (investment-profile-builder has inv_profile_builder_key.py);
    # Anthropic.py / api_key.py are the legacy and CI-runner names.
    anth = _find_module(
        ["projects/investment-forecaster/anthropic_key.py", "inv_forecaster_key.py",
         "Anthropic.py", "api_key.py"],
        "_secrets_anthropic",
    )
    # Assigned, not setdefault: the Secrets file is the single source of truth for
    # this key. With setdefault a stale ANTHROPIC_API_KEY left in the OS/user
    # environment silently won over the file, producing 401s no matter what the
    # file contained.
    os.environ["ANTHROPIC_API_KEY"] = anth.ANTHROPIC_API_KEY

    sec = _find_module(["shared/sec/edgar_user_agent.py", "SEC.py", "sec_id.py"], "_secrets_sec")
    sec_agent = getattr(sec, "SEC_EDGAR_USER_AGENT", None) or getattr(sec, "SEC_USER_AGENT", None)
    os.environ.setdefault("SEC_EDGAR_USER_AGENT", sec_agent)


_load()
