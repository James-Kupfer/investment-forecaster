"""
Sync personas/*.md into prompt_registry: reseed any agent whose file content
differs from what is currently active in the DB.

Editing a persona .md file and merging it to develop does NOT change agent
behavior on its own -- BaseAgent.get_active_prompt() reads prompt_text from
prompt_registry, not from the file. This script closes that gap by hashing
each personas/<agent_id>.md and comparing it to the DB's active version for
that agent_id, reseeding (via update_prompt.update_prompt(), the same
deactivate-old/insert-new path update_prompt.py uses) whenever they differ.

Validates changes by content hash, not by a human-maintained version marker.
A hand-written '## Version: X.Y' comment can go stale -- someone edits the
prompt body and forgets to bump it, and a marker-diff sync silently skips
the change. A hash of prompt_text can't go stale the same way: it changes
if and only if the content changes, so drift is always caught.

Idempotent and safe to run on every pipeline invocation: agents whose file
content hash already matches the active DB row are no-ops. Hash-derived
versions are tracked independently per agent_id, same as the old scheme --
there's no requirement that every agent share one version.

Usage:
    python scripts/sync_prompts.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from forecaster.db import db_cursor
from update_prompt import update_prompt

AGENTS_DIR = Path(__file__).resolve().parent.parent / "personas"

# prompt_registry.prompt_version is VARCHAR(20) -- "h-" + 12 hex chars = 14,
# comfortably under the limit while still being collision-safe in practice.
_HASH_LEN = 12


def _content_version(text: str) -> str:
    """Deterministic version label derived from prompt_text content: 'h-'
    plus a truncated SHA-256 hex digest. Identical content always produces
    the same label; any content change produces a different one -- so
    comparing labels is equivalent to comparing content, without needing to
    fetch/compare the full prompt_text on every sync."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"h-{digest[:_HASH_LEN]}"


def sync() -> int:
    synced = 0
    for md_path in sorted(AGENTS_DIR.glob("*.md")):
        agent_id = md_path.stem
        file_text = md_path.read_text(encoding="utf-8").strip()
        new_version = _content_version(file_text)

        with db_cursor() as cur:
            cur.execute(
                "SELECT prompt_version FROM prompt_registry "
                "WHERE agent_id = %s AND is_active = TRUE",
                (agent_id,),
            )
            row = cur.fetchone()
        db_version = row[0] if row else None

        if db_version == new_version:
            continue  # content hash unchanged -- nothing to reseed

        print(f"  {agent_id}: {db_version or '(none)'} -> {new_version}")
        update_prompt(agent_id, new_version, file_text)
        synced += 1

    return synced


if __name__ == "__main__":
    print("Syncing prompt_registry from personas/*.md ...")
    count = sync()
    print("Done." if count == 0 else f"Done. Reseeded {count} agent(s).")
