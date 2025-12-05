from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class RunRequest:
    user_prompt: str
    system_prompt_file: Optional[str] = None
    max_output_tokens: Optional[int] = None

@dataclass
class RunResult:
    ok: bool
    output_text: str
    raw_response: Any = None
    model: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    parsed_json: Optional[Any] = None  # best-effort JSON parse

@dataclass
class ExpectedSpec:
    # One of the following can be set depending on evaluation mode
    exact_text: Optional[str] = None
    equals_json: Optional[Any] = None
    json_subset: Optional[Any] = None
    regex: Optional[str] = None
    llm_judge: Optional[LLMJudgeSpec] = None

@dataclass
class EvalResult:
    passed: bool
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMJudgeGold:
    answer_text: Optional[str] = None
    answer_json: Optional[Any] = None
    numeric: Optional[float] = None
    reasoning: Optional[str] = None
    queries: Optional[List[str]] = None


@dataclass
class LLMJudgeSpec:
    gold: LLMJudgeGold
    weights: Dict[str, float] = field(default_factory=lambda: {
        "correctness": 0.7, "reasoning": 0.2, "efficiency": 0.1
    })
    pass_threshold: float = 0.8
    grading_mode: str = "gated"           # "gated" | "hierarchical" | "weighted"
    min_correctness: float = 1.0
    efficiency_budget: Optional[int] = None
    notes: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMJudgeSpec":
        gold_data = data.get("gold") or {}
        gold = LLMJudgeGold(
            answer_text=gold_data.get("answer_text"),
            answer_json=gold_data.get("answer_json"),
            numeric=gold_data.get("numeric"),
            reasoning=gold_data.get("reasoning"),
            queries=gold_data.get("queries") or [],
        )
        return cls(
            gold=gold,
            weights=data.get("weights") or {"correctness": 0.7, "reasoning": 0.2, "efficiency": 0.1},
            pass_threshold=float(data.get("pass_threshold", 0.8)),
            grading_mode=data.get("grading_mode", "gated"),
            min_correctness=float(data.get("min_correctness", 1.0)),
            efficiency_budget=data.get("efficiency_budget"),
            notes=data.get("notes"),
        )