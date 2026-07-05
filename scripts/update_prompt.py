"""
Update or add a prompt version for a specific agent in prompt_registry.

Deactivates the old active prompt (if any) and inserts a new one.
Useful for iterative prompt refinement on an already-seeded database.

Usage:
    python scripts/update_prompt.py --agent elicitation --version v1.2 --text "new prompt text..."
    python scripts/update_prompt.py --agent momentum --version v1.1 --file /path/to/prompt.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecaster.db import db_cursor


def update_prompt(agent_id: str, version: str, prompt_text: str) -> None:
    """Deactivate old active prompt for agent, insert new prompt with given version."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE prompt_registry SET is_active = 0 WHERE agent_id = ? AND is_active = 1",
            agent_id,
        )
        deactivated = cur.rowcount
        if deactivated > 0:
            print(f"  deactivated {deactivated} old active prompt(s) for {agent_id}")

        cur.execute(
            """
            INSERT INTO prompt_registry
                (agent_id, prompt_version, prompt_text, authored_by_model, is_active)
            VALUES (?, ?, ?, 'update_prompt_script', 1)
            """,
            agent_id,
            version,
            prompt_text,
        )
        print(f"  seeded {agent_id} ({version})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update a prompt in the prompt_registry table."
    )
    parser.add_argument("--agent", required=True, help="Agent ID (e.g., 'elicitation')")
    parser.add_argument("--version", required=True, help="Prompt version (e.g., 'v1.1')")
    parser.add_argument("--text", help="Prompt text (if not using --file)")
    parser.add_argument("--file", help="Path to file containing prompt text")

    args = parser.parse_args()

    if args.text:
        prompt_text = args.text
    elif args.file:
        try:
            prompt_text = Path(args.file).read_text()
        except FileNotFoundError:
            print(f"Error: file not found: {args.file}")
            return 1
    else:
        print("Error: must provide either --text or --file")
        return 1

    try:
        update_prompt(args.agent, args.version, prompt_text)
        print("Done.")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
