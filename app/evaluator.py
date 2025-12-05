import json
import re
import logging
from typing import Any, Dict, Optional, Tuple

from openai import OpenAI
from app.config import AppConfig
from app.types import RunResult, ExpectedSpec, EvalResult, LLMJudgeSpec

logger = logging.getLogger("evaluator")

def _json_equal(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

def _json_is_subset(small: Any, big: Any) -> bool:
    if isinstance(small, dict) and isinstance(big, dict):
        return all(k in big and _json_is_subset(v, big[k]) for k, v in small.items())
    if isinstance(small, list) and isinstance(big, list):
        return all(any(_json_is_subset(s, b) for b in big) for s in small)
    return small == big

# --- NEW: helpers to extract text/JSON from Responses API ---

def _response_to_text(resp) -> str:
    # 1) official convenience if available
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t
    # 2) walk output items and collect text content
    try:
        parts = []
        for item in getattr(resp, "output", []) or []:
            content = getattr(item, "content", None)
            if not content:
                continue
            for c in content:
                # SDK structs often have c.text or c.text.value
                txt = None
                if hasattr(c, "text"):
                    v = c.text
                    txt = getattr(v, "value", v) if v is not None else None
                elif hasattr(c, "input_text"):
                    v = c.input_text
                    txt = getattr(v, "value", v) if v is not None else None
                if isinstance(txt, str):
                    parts.append(txt)
        if parts:
            return "".join(parts)
    except Exception:
        pass
    # 3) last resort
    return str(resp)

def _extract_json_object(text: str) -> Optional[Any]:
    # Fast path
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip code fences if present
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Heuristic: take first balanced {...}
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None

# ------------------------------------------------------------

def _build_client(cfg: AppConfig) -> OpenAI:
    return OpenAI(api_key=cfg.openai_api_key)

def _eval_exact_text(output: RunResult, expected: ExpectedSpec) -> EvalResult:
    return EvalResult(passed=(output.output_text.strip() == (expected.exact_text or "").strip()))

def _eval_regex(output: RunResult, expected: ExpectedSpec) -> EvalResult:
    import re
    pat = expected.regex or ""
    ok = re.search(pat, output.output_text or "") is not None
    return EvalResult(passed=ok)

def _eval_equals_json(output: RunResult, expected: ExpectedSpec) -> EvalResult:
    try:
        got = output.parsed_json if output.parsed_json is not None else json.loads(output.output_text)
    except Exception:
        return EvalResult(passed=False, reason="output is not valid JSON")
    return EvalResult(passed=(got == expected.equals_json))

def _eval_json_subset(output: RunResult, expected: ExpectedSpec) -> EvalResult:
    try:
        got = output.parsed_json if output.parsed_json is not None else json.loads(output.output_text)
    except Exception:
        return EvalResult(passed=False, reason="output is not valid JSON")
    # mínima implementación: igualdad directa por ahora
    return EvalResult(passed=(got == expected.json_subset))

def _eval_llm_judge(cfg: AppConfig, output: RunResult, expected: ExpectedSpec) -> EvalResult:
    assert expected.llm_judge is not None
    spec: LLMJudgeSpec = expected.llm_judge
    client = _build_client(cfg)

    payload: Dict[str, Any] = {
        "user_prompt": output.metadata.get("user_prompt"),
        "model_answer_text": output.output_text,
        "model_answer_json": output.parsed_json,
        "mcp_trace": output.metadata.get("mcp_trace"),
        "gold": spec.gold.__dict__,
        "weights": spec.weights,
        "pass_threshold": spec.pass_threshold,
        "grading_mode": spec.grading_mode,
        "min_correctness": spec.min_correctness,
        "efficiency_budget": spec.efficiency_budget,
        "notes": spec.notes,
    }

    logger.debug("LLM-judge input:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))

    resp = client.responses.create(
        model=cfg.judge_model,
        input=json.dumps(payload, ensure_ascii=False),
        instructions=cfg.load_judge_prompt(),
        max_output_tokens=30000,
    )

    output_text = getattr(resp, "output_text", None) or str(resp)
    logger.debug("LLM-judge raw output_text:\n%s", output_text)

    try:
        verdict = json.loads(output_text)
    except Exception:
        return EvalResult(passed=False, reason="Judge response is not valid JSON")

    passed = (verdict.get("verdict") == "pass")
    reason = verdict.get("feedback_short") or verdict.get("reason")
    return EvalResult(passed=passed, reason=reason, details=verdict)

def evaluate(cfg: AppConfig, output: RunResult, expected: ExpectedSpec) -> EvalResult:
    if expected.exact_text is not None:
        return _eval_exact_text(output, expected)
    if expected.regex is not None:
        return _eval_regex(output, expected)
    if expected.equals_json is not None:
        return _eval_equals_json(output, expected)
    if expected.json_subset is not None:
        return _eval_json_subset(output, expected)
    if expected.llm_judge is not None:
        return _eval_llm_judge(cfg, output, expected)
    return EvalResult(passed=False, reason="No evaluation mode specified")


def evaluate_llm_judge(cfg: AppConfig, output: RunResult, spec: LLMJudgeSpec) -> EvalResult:
    # wrapper directo
    return _eval_llm_judge(cfg, output, ExpectedSpec(llm_judge=spec))

