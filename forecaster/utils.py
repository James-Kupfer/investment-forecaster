import json
import re


def extract_json(text: str) -> dict:
    """Extract the first JSON object from LLM response text."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # ```json ... ``` fenced block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # First bare { ... }
    match = re.search(r'\{.*\}', stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}
