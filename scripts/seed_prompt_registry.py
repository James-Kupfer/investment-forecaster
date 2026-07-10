"""
Seed substantive v1.1 prompts for all pipeline agents into prompt_registry.

Prompt text is loaded from forecaster/agents/{agent_id}.md files.
Idempotent: skips any agent_id that already has an active prompt.
Run once after migrations, or whenever a new agent is added.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecaster.db import db_cursor

AGENTS_DIR = Path(__file__).resolve().parent.parent / "forecaster" / "agents"

STUBS: list[dict] = [
    {"agent_id": "question_definition", "prompt_version": "v1.1"},
    {"agent_id": "macroq",             "prompt_version": "v1.1"},
    {"agent_id": "risk_judge",         "prompt_version": "v1.1"},
    {"agent_id": "earnings",           "prompt_version": "v1.1"},
    {"agent_id": "primary_source",     "prompt_version": "v1.1"},
    {"agent_id": "momentum",           "prompt_version": "v1.1"},
    {"agent_id": "trend",              "prompt_version": "v1.1"},
    {"agent_id": "volume",             "prompt_version": "v1.1"},
    {"agent_id": "pattern",            "prompt_version": "v1.1"},
    {"agent_id": "tech_judge",         "prompt_version": "v1.1"},
    {"agent_id": "elicitation",        "prompt_version": "v1.1"},
    {"agent_id": "review",             "prompt_version": "v1.1"},
    {"agent_id": "confidence_judge",   "prompt_version": "v1.1"},
    {"agent_id": "aggregation",        "prompt_version": "v1.1"},
]


def seed() -> None:
    with db_cursor() as cur:
        for stub in STUBS:
            agent_id = stub["agent_id"]
            cur.execute(
                "SELECT COUNT(*) FROM prompt_registry WHERE agent_id = %s AND is_active = TRUE",
                (agent_id,),
            )
            count = cur.fetchone()[0]
            if count > 0:
                print(f"  skip  {agent_id} (active prompt exists)")
                continue
            md_path = AGENTS_DIR / f"{agent_id}.md"
            prompt_text = md_path.read_text(encoding="utf-8").strip()
            cur.execute(
                """
                INSERT INTO prompt_registry
                    (agent_id, prompt_version, prompt_text, authored_by_model, is_active)
                VALUES (%s, %s, %s, 'seed_v1.1', TRUE)
                """,
                (agent_id, stub["prompt_version"], prompt_text),
            )
            print(f"  seeded {agent_id} ({stub['prompt_version']})")


if __name__ == "__main__":
    print("Seeding prompt_registry...")
    seed()
    print("Done.")
