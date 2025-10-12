import json
import re
from typing import Any, Tuple
from app.types import RunResult, ExpectedSpec, EvalResult

def _json_equal(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

def _json_is_subset(small: Any, big: Any) -> bool:
    if isinstance(small, dict) and isinstance(big, dict):
        return all(k in big and _json_is_subset(v, big[k]) for k, v in small.items())
    if isinstance(small, list) and isinstance(big, list):
        # every element in small must appear as a subset in some element in big
        return all(any(_json_is_subset(s, b) for b in big) for s in small)
    return small == big

def evaluate(result: RunResult, expected: ExpectedSpec) -> EvalResult:
    if not result.ok:
        return EvalResult(passed=False, reason=f"Run failed: {result.error}")

    text = result.output_text or ""

    # 1) exact text
    if expected.exact_text is not None:
        passed = text == expected.exact_text
        return EvalResult(passed=passed, reason=None if passed else "exact_text mismatch")

    # 2) equals_json
    if expected.equals_json is not None:
        if result.parsed_json is None:
            return EvalResult(passed=False, reason="output is not valid JSON")
        passed = _json_equal(result.parsed_json, expected.equals_json)
        return EvalResult(passed=passed, reason=None if passed else "equals_json mismatch")

    # 3) json_subset
    if expected.json_subset is not None:
        if result.parsed_json is None:
            return EvalResult(passed=False, reason="output is not valid JSON")
        passed = _json_is_subset(expected.json_subset, result.parsed_json)
        return EvalResult(passed=passed, reason=None if passed else "json_subset mismatch")

    # 4) regex
    if expected.regex is not None:
        passed = re.search(expected.regex, text, re.DOTALL) is not None
        return EvalResult(passed=passed, reason=None if passed else "regex mismatch")

    return EvalResult(passed=False, reason="No evaluation criterion provided")