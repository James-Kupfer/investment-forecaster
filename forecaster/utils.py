import json
import re


def extract_json(text: str) -> dict:
    """Extract the first JSON object from LLM response text."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # ```json ... ``` fenced block — use greedy inner match so nested braces aren't cut short
    match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Scan character-by-character to find the outermost balanced { ... } block
    start = stripped.find('{')
    if start != -1:
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(stripped[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return {}
