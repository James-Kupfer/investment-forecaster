import json
import re


def extract_json(text: str) -> dict:
    """
    Extract a JSON object from LLM response text. Prefers the candidate with
    the MOST keys, not simply the last one: models occasionally emit a draft
    object, then narrate a self-correction ("...correcting to the required
    schema:") followed by a second, complete object, and the more-complete
    one is what was actually intended (ties go to the later candidate, which
    still favors a self-correction over its draft). A strictly-last-wins rule
    is not safe on its own — observed live on a confidence_judge response that
    included the literal aside "Elicitation agent output is empty ({})" in
    its trailing prose; the brace-depth scanner below correctly parses that
    "{}" as a valid empty top-level object, and being last, it would silently
    discard the real, complete answer that preceded it.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    candidates: list[str] = []
    # All ```json ... ``` fenced blocks, in order of appearance.
    candidates.extend(re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', stripped, re.DOTALL))

    # All top-level balanced { ... } blocks found by brace-depth scanning
    # (handles unfenced JSON, including multiple objects in one response).
    depth = 0
    in_string = False
    escape_next = False
    start = None
    for i, ch in enumerate(stripped):
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
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(stripped[start:i + 1])
                start = None

    result: dict = {}
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and len(parsed) >= len(result):
            result = parsed  # most keys wins; later candidate breaks ties
    return result
