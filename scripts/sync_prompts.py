"""
Sync personas/*.md into prompt_registry: reseed any agent whose file content
differs from what is currently active in the DB.

Editing a persona .md file and merging it to develop does NOT change agent
behavior on its own -- BaseAgent.get_active_prompt() reads prompt_text from
prompt_registry, not from the file. This script closes that gap by diffing
each personas/<agent_id>.md against the DB's active row for that agent_id
and reseeding (via update_prompt.update_prompt(), the same deactivate-old/
insert-new path update_prompt.py uses) whenever they differ.

Diffs on actual prompt_text content, not just the in-file version marker
('## Version: X.Y' or '<version>X.Y</version>') -- a persona edited without
remembering to bump its version marker still gets picked up; the mismatch
is logged as a warning rather than silently skipped.

Idempotent and safe to run on every pipeline invocation: agents whose file
content already matches the active DB row are no-ops. Versions are tracked
independently per agent_id (e.g. aggregation.md may be v2.5 while others
sit at v2.4) -- this is normal, not a sync failure.

Usage:
    python scripts/sync_prompts.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from forecaster.db import db_cursor
from update_prompt import update_prompt

AGENTS_DIR = Path(__file__).resolve().parent.parent / "personas"

_TOP_VERSION_RE = re.compile(r"^## Version:\s*(\S+)\s*$", re.MULTILINE)
_BOTTOM_VERSION_RE = re.compile(r"<version>\s*(\S+)\s*</version>")
_NUMERIC_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)$", re.IGNORECASE)


def _extract_version(text: str) -> str | None:
    """Parse a persona file's version marker. Tolerant of the two
    conventions in use ('## Version: X.Y' at the top, '<version>X.Y</version>'
    at the bottom) and of an optional leading 'v' (aggregation.md uses
    'v2.5'; every other file uses a bare number)."""
    m = _TOP_VERSION_RE.search(text) or _BOTTOM_VERSION_RE.search(text)
    if not m:
        return None
    vm = _NUMERIC_VERSION_RE.match(m.group(1))
    return f"{vm.group(1)}.{vm.group(2)}" if vm else m.group(1).lstrip("vV")


def _next_version(current: str | None) -> str:
    """Bump the minor component of a vX.Y DB version string. Falls back to
    v1.1 if the active version isn't in that shape (e.g. no prior row)."""
    if current:
        m = _NUMERIC_VERSION_RE.match(current)
        if m:
            return f"v{m.group(1)}.{int(m.group(2)) + 1}"
    return "v1.1"


def sync() -> int:
    synced = 0
    for md_path in sorted(AGENTS_DIR.glob("*.md")):
        agent_id = md_path.stem
        file_text = md_path.read_text(encoding="utf-8").strip()

        with db_cursor() as cur:
            cur.execute(
                "SELECT prompt_version, prompt_text FROM prompt_registry "
                "WHERE agent_id = %s AND is_active = TRUE",
                (agent_id,),
            )
            row = cur.fetchone()
        db_version, db_text = row if row else (None, None)

        if db_text is not None and db_text.strip() == file_text:
            continue  # content identical -- nothing to reseed

        file_version = _extract_version(file_text)
        candidate = f"v{file_version}" if file_version else None
        if candidate and candidate != db_version:
            new_version = candidate
        else:
            # Either no parseable marker, or the marker wasn't bumped despite
            # a real content change -- never reuse a version label for two
            # different prompt_text bodies.
            if candidate:
                print(
                    f"  WARNING: {agent_id} content changed but its version "
                    f"marker still reads {candidate} (same as the active DB "
                    f"version) -- auto-bumping instead of reusing a stale "
                    f"label. Update the marker in personas/{agent_id}.md."
                )
            new_version = _next_version(db_version)

        print(f"  {agent_id}: {db_version or '(none)'} -> {new_version}")
        update_prompt(agent_id, new_version, file_text)
        synced += 1

    return synced


if __name__ == "__main__":
    print("Syncing prompt_registry from personas/*.md ...")
    count = sync()
    print("Done." if count == 0 else f"Done. Reseeded {count} agent(s).")
