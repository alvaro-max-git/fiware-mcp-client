from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.mcp_launcher import MCPServerState
from app.core.types import RunResult


SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
)


def _stringify_unknown(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=_stringify_unknown))
    except Exception:
        return str(value)


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                redacted[key_text] = "[redacted]"
            else:
                redacted[key_text] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class MCPTrace(BaseModel):
    calls: List[Dict[str, Any]] = Field(default_factory=list)
    call_count: int = 0
    queries: List[str] = Field(default_factory=list)
    usage: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Any) -> "MCPTrace":
        data = raw if isinstance(raw, dict) else {}

        calls_raw = data.get("calls")
        calls = calls_raw if isinstance(calls_raw, list) else []

        queries_raw = data.get("queries")
        queries = [str(item) for item in queries_raw] if isinstance(queries_raw, list) else []

        usage_raw = data.get("usage")
        usage = usage_raw if isinstance(usage_raw, dict) else {}

        call_count_raw = data.get("call_count")
        call_count = call_count_raw if isinstance(call_count_raw, int) else len(calls)

        return cls(
            calls=_redact_sensitive(_json_safe(calls)),
            call_count=call_count,
            queries=queries,
            usage=_redact_sensitive(_json_safe(usage)),
        )


class RunResponse(BaseModel):
    ok: bool
    output_text: str
    model_name: Optional[str] = None
    error: Optional[str] = None
    parsed_json: Optional[Any] = None
    mcp_trace: MCPTrace = Field(default_factory=MCPTrace)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_result(cls, result: RunResult) -> "RunResponse":
        metadata = dict(result.metadata or {})
        raw_trace = metadata.pop("mcp_trace", None) or metadata.pop("mcp_traces", None)
        safe_metadata = _redact_sensitive(_json_safe(metadata))

        return cls(
            ok=result.ok,
            output_text=result.output_text,
            model_name=str(result.model_name) if result.model_name is not None else None,
            error=result.error,
            parsed_json=_redact_sensitive(_json_safe(result.parsed_json)),
            mcp_trace=MCPTrace.from_raw(raw_trace),
            metadata=safe_metadata if isinstance(safe_metadata, dict) else {},
        )


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class RuntimeFeatures(BaseModel):
    run: bool = True
    chat: bool = True
    streaming: bool = True
    mcp_server_management: bool = True
    evaluation: bool = False
    benchmark: bool = False


class RuntimeResponse(BaseModel):
    base_url: str
    read_only: bool
    default_agent_id: Optional[str] = None
    profiles_yaml: Optional[str] = None
    tools_yaml: Optional[str] = None
    features: RuntimeFeatures = Field(default_factory=RuntimeFeatures)


class AgentInfo(BaseModel):
    id: str
    description: Optional[str] = None
    backend_type: str
    model_name: str
    tools: List[str] = Field(default_factory=list)
    supports_sessions: bool
    supports_streaming: bool


class AgentsResponse(BaseModel):
    default_agent_id: str
    agents: List[AgentInfo]


class PromptTurnRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    max_output_tokens: Optional[int] = Field(default=None, gt=0)

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("prompt must not be empty")
        return stripped

    @field_validator("agent_id", "session_id")
    @classmethod
    def _blank_optional_strings_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


ContextUrl = Literal["context-data-loader", "mcp-experiments"]


class MCPServerStartRequest(BaseModel):
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=5001, gt=0, le=65535)
    context_url: ContextUrl = "context-data-loader"
    timeout_seconds: float = Field(default=10, gt=0)
    wait: bool = True


class MCPServerStopRequest(BaseModel):
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=5001, gt=0, le=65535)
    timeout_seconds: float = Field(default=5, gt=0)


class MCPServerRestartRequest(BaseModel):
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=5001, gt=0, le=65535)
    context_url: ContextUrl = "context-data-loader"
    timeout_seconds: float = Field(default=10, gt=0)


class MCPServerStateResponse(BaseModel):
    running: bool
    reachable: bool
    managed: bool
    endpoint: str
    pid: Optional[int] = None
    pid_file: Optional[str] = None
    log_file: Optional[str] = None
    message: str

    @classmethod
    def from_state(cls, state: MCPServerState) -> "MCPServerStateResponse":
        return cls(
            running=state.running,
            reachable=state.reachable,
            managed=state.managed,
            endpoint=state.endpoint,
            pid=state.pid,
            pid_file=str(state.pid_file) if state.pid_file else None,
            log_file=str(state.log_file) if state.log_file else None,
            message=state.message,
        )

