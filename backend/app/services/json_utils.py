"""Shared JSON utilities — used by PrepAgent, Evaluator, and PostAgent.

Extracts JSON from LLM output that may contain markdown fences, extra text,
or malformed wrapping.
"""

import json as _json


def extract_json(text: str) -> dict | list:
    """Robust JSON extraction from LLM output.

    Handles: extra text after JSON, markdown code fences, nested brackets.
    Returns empty dict on failure.

    Used by:
        - PrepAgent: extract question list from resume-driven generation
        - EvaluatorAgent: extract structured assessment
        - PostAgent: extract scorecard
    """
    if not text or not text.strip():
        return {}

    # First try: parse the whole thing
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass

    # Strip markdown fences
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        # Remove opening fence (``` or ```json) and closing fence
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        clean = "\n".join(inner)

    # Try parsing after stripping fences
    try:
        return _json.loads(clean)
    except _json.JSONDecodeError:
        pass

    # Try to find the first complete JSON object or array by bracket matching
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == start_char:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        return _json.loads(text[start:i + 1])
                    except _json.JSONDecodeError:
                        break  # Try the other bracket type

    return {}
