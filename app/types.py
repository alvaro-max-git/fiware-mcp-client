from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

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

@dataclass
class EvalResult:
    passed: bool
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)