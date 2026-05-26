import json
import re
import logging
from typing import Any, Optional

from app.core.config import AppConfig
from app.core.types import RunRequest, RunResult, ExpectedSpec, EvalResult, LLMJudgeSpec
from app.services.run_service import RunService

logger = logging.getLogger("evaluator")

def _json_equal(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

def _json_is_subset(small: Any, big: Any) -> bool:
    if isinstance(small, dict) and isinstance(big, dict):
        return all(k in big and _json_is_subset(v, big[k]) for k, v in small.items())
    if isinstance(small, list) and isinstance(big, list):
        return all(any(_json_is_subset(s, b) for b in big) for s in small)
    return small == big

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


def evaluate_llm_judge(
    cfg: AppConfig,
    result: RunResult,
    spec: LLMJudgeSpec,
    user_prompt: Optional[str] = None,
    *,
    profiles_yaml: Optional[str] = None,
    tools_yaml: Optional[str] = None,
    judge_agent_id: Optional[str] = None,
) -> EvalResult:
    judge_input = _build_judge_input(result, spec, user_prompt)

    if logger.isEnabledFor(logging.DEBUG):
        try:
            logger.debug("LLM-judge input:\n%s", json.dumps(judge_input, ensure_ascii=False, indent=2))
        except Exception:
            logger.debug("LLM-judge input (raw, non-serializable): %s", str(judge_input)[:2000])

    run_service = RunService(cfg)

    # Prefer evaluator agent from YAML if provided; otherwise legacy no-tool judge path.
    judge_result: RunResult
    if profiles_yaml:
        judge_id = judge_agent_id or "fiware-evaluator"
        judge_result = run_service.run_turn(
            RunRequest(
                user_prompt=json.dumps(judge_input, ensure_ascii=False),
                profiles_yaml=profiles_yaml,
                tools_yaml=tools_yaml,
                agent_id=judge_id,
                max_output_tokens=30000,
            )
        )
        if not judge_result.ok:
            logger.warning("Falling back to legacy judge because evaluator agent failed: %s", judge_result.error)
            judge_result = _legacy_judge_request(run_service, cfg, judge_input)
    else:
        judge_result = _legacy_judge_request(run_service, cfg, judge_input)

    if not judge_result.ok:
        return EvalResult(
            passed=False,
            reason=f"judge run failed: {judge_result.error}",
            details={"raw": judge_result.output_text},
        )

    out_text = judge_result.output_text
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("LLM-judge raw output_text:\n%s", out_text)

    # Intentar parsear JSON robustamente
    judge_json = _extract_json_object(out_text)
    if judge_json is None:
        return EvalResult(
            passed=False,
            reason="judge did not return valid JSON",
            details={"raw": out_text}
        )

    verdict = str(judge_json.get("verdict", "")).lower() == "pass"
    feedback = judge_json.get("feedback_short")
    return EvalResult(passed=verdict, reason=feedback, details=judge_json)


def _legacy_judge_request(run_service: RunService, cfg: AppConfig, judge_input: dict) -> RunResult:
    return run_service.run_turn(
        RunRequest(
            user_prompt=json.dumps(judge_input, ensure_ascii=False),
            model_name=cfg.judge_model,
            system_prompt_file=cfg.judge_system_prompt_file,
            max_output_tokens=30000,
            use_tools=False,
            include_runtime_instructions=False,
        )
    )


def _build_judge_input(result: RunResult, spec: LLMJudgeSpec, user_prompt: Optional[str]) -> dict:
    meta = result.metadata or {}
    prompt_value = user_prompt or meta.get("user_prompt") or getattr(result.raw_response, "input", None)
    trace = meta.get("mcp_trace") or meta.get("mcp_traces") or {}
    return {
        "user_prompt": prompt_value,
        "model_answer_text": result.output_text,
        "model_answer_json": result.parsed_json,
        "mcp_trace": trace,
        "gold": {
            "answer_text": spec.gold.answer_text,
            "answer_json": spec.gold.answer_json,
            "numeric": spec.gold.numeric,
            "reasoning": spec.gold.reasoning,
            "queries": spec.gold.queries or [],
        },
        "weights": spec.weights,
        "pass_threshold": spec.pass_threshold,
        "efficiency_budget": spec.efficiency_budget,
        "notes": spec.notes,
        "grading_mode": spec.grading_mode,
        "min_correctness": spec.min_correctness
    }

