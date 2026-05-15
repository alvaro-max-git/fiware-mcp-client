from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, Field

from app.core.model_name import ModelName


class RunRequest(BaseModel):
    user_prompt: str
    system_prompt_file: Optional[str] = None
    max_output_tokens: Optional[int] = None
    profiles_yaml: Optional[str] = None
    tools_yaml: Optional[str] = None
    agent_id: Optional[str] = None


class RunResult(BaseModel):
    ok: bool
    output_text: str
    raw_response: Any = None
    model_name: Optional[ModelName] = Field(
        default=None,
        validation_alias=AliasChoices("model_name", "model"),
    )
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    parsed_json: Optional[Any] = None

    @property
    def model(self) -> Optional[str]:
        """Compatibility accessor for older benchmark and CLI code."""

        return self.model_name


class LLMJudgeGold(BaseModel):
    answer_text: Optional[str] = None
    answer_json: Optional[Any] = None
    numeric: Optional[float] = None
    reasoning: Optional[str] = None
    queries: Optional[List[str]] = None


class LLMJudgeSpec(BaseModel):
    gold: LLMJudgeGold
    weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "correctness": 0.7,
            "reasoning": 0.2,
            "efficiency": 0.1,
        }
    )
    pass_threshold: float = 0.8
    efficiency_budget: Optional[int] = None
    notes: Optional[str] = None

    grading_mode: str = "gated"
    min_correctness: float = 1.0

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "LLMJudgeSpec":
        if not isinstance(data, dict):
            raise ValueError("--llm-judge expects a JSON object")

        gold_data = data.get("gold")
        if not isinstance(gold_data, dict):
            raise ValueError("--llm-judge payload requires a 'gold' object")

        queries = gold_data.get("queries")
        if queries is not None and not isinstance(queries, list):
            raise ValueError("'gold.queries' must be a list")

        numeric = gold_data.get("numeric")
        if numeric is not None:
            numeric = float(numeric)

        gold = LLMJudgeGold(
            answer_text=gold_data.get("answer_text"),
            answer_json=gold_data.get("answer_json"),
            numeric=numeric,
            reasoning=gold_data.get("reasoning"),
            queries=[str(q) for q in queries] if queries is not None else None,
        )

        weights_obj = data.get("weights")
        if weights_obj is not None and not isinstance(weights_obj, dict):
            raise ValueError("'weights' must be an object")
        weights = {"correctness": 0.7, "reasoning": 0.2, "efficiency": 0.1}
        if isinstance(weights_obj, dict):
            weights = {str(k): float(v) for k, v in weights_obj.items()}

        eff_budget = data.get("efficiency_budget")
        if eff_budget is not None:
            eff_budget = int(eff_budget)

        pass_threshold = data.get("pass_threshold")
        pass_threshold = float(pass_threshold) if pass_threshold is not None else 0.8

        grading_mode = data.get("grading_mode")
        grading_mode = str(grading_mode) if grading_mode is not None else "gated"

        min_correctness = data.get("min_correctness")
        min_correctness = float(min_correctness) if min_correctness is not None else 1.0

        notes = data.get("notes")
        if notes is not None:
            notes = str(notes)

        return LLMJudgeSpec(
            gold=gold,
            weights=weights,
            pass_threshold=pass_threshold,
            efficiency_budget=eff_budget,
            notes=notes,
            grading_mode=grading_mode,
            min_correctness=min_correctness,
        )


class ExpectedSpec(BaseModel):
    exact_text: Optional[str] = None
    equals_json: Optional[Any] = None
    json_subset: Optional[Any] = None
    regex: Optional[str] = None
    llm_judge: Optional[LLMJudgeSpec] = None


class EvalResult(BaseModel):
    passed: bool
    reason: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
