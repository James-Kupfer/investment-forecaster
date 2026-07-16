"""Local configuration for the forecaster package, loaded from config.toml at
the repo root -- git-ignored, machine-specific; see config.example.toml for
the template. config.toml is the first choice for configuring this project.

FORECASTER_SECRETS_DIR is an additional escape hatch, checked before
config.toml, for environments where a checked-out file can't be relied on to
persist -- e.g. a self-hosted CI runner whose working directory gets
`git clean`ed between runs (actions/checkout's default `clean: true` removes
git-ignored files too). Set it the same way CLAUDE.md has you set
PYTHONUTF8 -- `setx FORECASTER_SECRETS_DIR "C:\\path\\to\\Secrets"` -- once on
that machine, not in any tracked file. Accepts os.pathsep-separated entries
for more than one candidate directory.

Real OS environment variables (DB_PORT, DB_NAME, PORTFOLIO_DB_NAME,
IBKR_GATEWAY_URL) still override the [database]/[market_data] values below
when set -- see forecaster/db.py and forecaster/market_data.py.

DATABASE/MARKET_DATA are merged from config.example.toml (base) then
config.toml (override), NOT hardcoded a second time as Python literals in
db.py/market_data.py -- config.example.toml's [database]/[market_data]
values (port 5432, db names, the local IBKR gateway URL) are genuine,
universally-safe defaults, not machine-specific placeholders, so they're
exactly what a fresh checkout with no config.toml yet should fall back to.
SECRETS_DIRS is deliberately NOT merged this way: config.example.toml's
[secrets] override is a placeholder path ("C:/Users/you/GitHub/Secrets")
that was never meant to be read for real, so an absent config.toml leaves
SECRETS_DIRS empty and credentials.py raises a clear "not configured" error
instead of silently trying (and failing) against that placeholder.
"""
import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config.toml"
_EXAMPLE_PATH = _REPO_ROOT / "config.example.toml"


class SecretsNotFoundError(FileNotFoundError):
    """The configured Secrets folder(s) don't contain a required file.

    Defined here (not in credentials.py, which raises it) so CLI entry
    points can import it without triggering credentials.py's module-level
    _load() side effect just to reference the exception type -- config.py
    never raises on import, it only reads config.toml (or returns {} if
    absent). Deliberately a distinct type, not a bare FileNotFoundError --
    scripts/*.py catch this specifically to print a clean, actionable
    message instead of a traceback, without risking silently swallowing an
    unrelated FileNotFoundError elsewhere."""


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


_example_config = _load_toml(_EXAMPLE_PATH)
_local_config = _load_toml(_CONFIG_PATH)

_env_override = os.environ.get("FORECASTER_SECRETS_DIR")
if _env_override:
    SECRETS_DIRS = _env_override.split(os.pathsep)
else:
    _toml_override = _local_config.get("secrets", {}).get("override", [])
    SECRETS_DIRS = [_toml_override] if isinstance(_toml_override, str) else list(_toml_override)

DATABASE = {**_example_config.get("database", {}), **_local_config.get("database", {})}
MARKET_DATA = {**_example_config.get("market_data", {}), **_local_config.get("market_data", {})}
