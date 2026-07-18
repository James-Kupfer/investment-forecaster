import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIDENCE_WORDS = {
    "high": "High",
    "medium": "Medium",
    "med": "Medium",
    "moderate": "Medium",
    "low": "Low",
}


def normalize_confidence_word(value: Optional[str], *, context: str) -> Optional[str]:
    """Normalize an LLM-produced confidence rating to exactly "High"/"Medium"/
    "Low", or None. Several forecasts columns storing these ratings
    (risk_judge_confidence, macroq_confidence, forecast_questions.confidence)
    are VARCHAR(10) -- writing an LLM's raw free text there unvalidated can
    crash the whole UPDATE with StringDataRightTruncation (observed live: a
    risk_judge response for CRGY), taking down the entire pipeline run for
    that symbol, not just this one column. Fails safe -- logs and returns
    None -- rather than truncating to something misleading or letting a bad
    value reach the DB raw."""
    if not value:
        return None
    normalized = _CONFIDENCE_WORDS.get(str(value).strip().lower())
    if normalized is None:
        logger.warning(
            "%s: unrecognized confidence value %r (expected high/medium/low) -- storing NULL",
            context, value,
        )
    return normalized


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
