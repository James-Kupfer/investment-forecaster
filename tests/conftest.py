"""Shared pytest setup.

Unit tests mock every external service, so they must not need production secrets
just to be *collected*: forecaster.credentials loads postgres.py, an Anthropic key
file and SEC.py from the Secrets folder at import time, and the self-hosted CI
runner's folder is missing some of them -- which aborted collection of the whole
suite with SecretsNotFoundError. _ensure_secrets() appends a directory of dummy
credentials as a LAST-resort search location: real files, where they exist, are
found first and win, so a developer machine (and tests/test_db.py, which talks to
the live database) keeps using the real ones.
"""
import tempfile
from pathlib import Path

from forecaster.config import SECRETS_DIRS

_STUB_FILES = {
    "postgres.py": 'dsn = "localhost"\npostgres_user = "test"\npostgres_password = "test"\n',
    "inv_forecaster_key.py": 'ANTHROPIC_API_KEY = "test-key-not-real"\n',
    "SEC.py": 'SEC_EDGAR_USER_AGENT = "unit-tests unit-tests@example.com"\n',
}


def _ensure_secrets() -> None:
    stub_dir = Path(tempfile.mkdtemp(prefix="forecaster-test-secrets-"))
    for name, content in _STUB_FILES.items():
        (stub_dir / name).write_text(content, encoding="utf-8")
    SECRETS_DIRS.append(str(stub_dir))  # same list object credentials.py searches


_ensure_secrets()

# test_image_extractor.py is disabled: it loads "Technical Analysis/image_extractor.py"
# at import time, and that folder is not in this repo, so collection of the whole
# suite aborted with FileNotFoundError. Remove this entry once the folder is restored.
collect_ignore = ["test_image_extractor.py"]
