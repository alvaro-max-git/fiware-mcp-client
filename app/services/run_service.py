from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, List, Optional

from openai import OpenAI

from app.core.agent_session import AgentSession
from app.core.config import AppConfig
from app.core.normalizers import (
    extract_mcp_trace_from_agents_result,
    extract_mcp_trace_from_response,
    extract_output_text,
    parse_output_json,
)
from app.core.types import RunRequest, RunResult
from app.core.model_name import normalize_model_name
from app.prompts import load_prompt
from app.tools.openai_responses_adapter import OpenAIResponsesToolAdapter, ToolLike

log = logging.getLogger("run_service")


class RunService:
    """Application service for one non-streaming model turn."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def run_turn(self, request: RunRequest) -> RunResult:
        try:
            if request.profiles_yaml:
                return self._run_yaml_mode(request)
            return self._run_legacy_mode(request)
        except Exception as exc:
            log.exception("RunService.run_turn failed")
            return RunResult(
                ok=False,
                output_text="",
                error=self._format_error(exc),
                model_name=request.model_name or self.cfg.model,
            )

    def stream_turn(
        self,
        request: RunRequest,
        *,
        on_text_delta: Callable[[str], None],
    ) -> RunResult:
        try:
            if not request.profiles_yaml:
                raise ValueError("Streaming chat requires YAML mode and a streaming-capable backend")
            return self._stream_yaml_mode(request, on_text_delta=on_text_delta)
        except Exception as exc:
            log.exception("RunService.stream_turn failed")
            return RunResult(
                ok=False,
                output_text="",
                error=self._format_error(exc),
                model_name=request.model_name or self.cfg.model,
            )

    def _run_yaml_mode(self, request: RunRequest) -> RunResult:
        session = AgentSession.from_yaml(
            yaml_path=Path(request.profiles_yaml or ""),
            default_agent=request.agent_id,
            prompts_dir=self.cfg.prompts_dir,
            read_only=self.cfg.read_only,
            tools_yaml=Path(request.tools_yaml) if request.tools_yaml else None,
        )
        agent = session.get_agent(request.agent_id)
        resp = session.ask(
            request.user_prompt,
            agent_id=request.agent_id,
            max_output_tokens=request.max_output_tokens or self.cfg.max_output_tokens,
            session_id=request.session_id,
        )
        return self._normalize_response(
            resp,
            model_name=getattr(agent.model_backend, "model_name", self.cfg.model),
            tools=agent.tools,
        )

    def _stream_yaml_mode(
        self,
        request: RunRequest,
        *,
        on_text_delta: Callable[[str], None],
    ) -> RunResult:
        session = AgentSession.from_yaml(
            yaml_path=Path(request.profiles_yaml or ""),
            default_agent=request.agent_id,
            prompts_dir=self.cfg.prompts_dir,
            read_only=self.cfg.read_only,
            tools_yaml=Path(request.tools_yaml) if request.tools_yaml else None,
        )
        agent = session.get_agent(request.agent_id)
        resp = session.ask_stream(
            request.user_prompt,
            agent_id=request.agent_id,
            max_output_tokens=request.max_output_tokens or self.cfg.max_output_tokens,
            session_id=request.session_id,
            on_text_delta=on_text_delta,
        )
        return self._normalize_response(
            resp,
            model_name=getattr(agent.model_backend, "model_name", self.cfg.model),
            tools=agent.tools,
        )

    def _run_legacy_mode(self, request: RunRequest) -> RunResult:
        model_name = normalize_model_name(request.model_name or self.cfg.model)
        tools: List[dict] = []
        if request.use_tools:
            tools = self.cfg.build_tools()
            if not tools:
                raise ValueError(
                    "No tools configured for legacy mode. Define MCP servers in config.yaml under 'mcp_servers' "
                    "(preferred), or use legacy env vars MCP_URL/MCP_LABEL (or MCP0_URL/MCP0_LABEL...) in .env. "
                    "Alternatively, run with --profiles-yaml (YAML-first mode)."
                )

        client = self._build_client()
        payload = {
            "model": model_name,
            "instructions": self._build_system_instructions(
                request.system_prompt_file,
                include_runtime_instructions=request.include_runtime_instructions,
            ),
            "input": request.user_prompt,
            "max_output_tokens": request.max_output_tokens or self.cfg.max_output_tokens,
        }
        if request.use_tools:
            payload["tools"] = tools  # type: ignore[assignment]

        resp = client.responses.create(**payload)
        return self._normalize_response(resp, model_name=model_name, tools=tools)

    def _normalize_response(
        self,
        resp: object,
        *,
        model_name: Optional[str],
        tools: List[ToolLike],
    ) -> RunResult:
        output_text = extract_output_text(resp)
        return RunResult(
            ok=True,
            output_text=output_text,
            raw_response=resp,
            model_name=model_name,
            parsed_json=parse_output_json(output_text),
            metadata={
                "tools": self._serialize_tools_for_metadata(tools),
                "mcp_trace": self._extract_mcp_trace(resp),
            },
        )

    def _extract_mcp_trace(self, resp: object) -> dict:
        if hasattr(resp, "new_items") and hasattr(resp, "raw_responses"):
            return extract_mcp_trace_from_agents_result(resp)
        return extract_mcp_trace_from_response(resp)

    def _serialize_tools_for_metadata(self, tools: List[ToolLike]) -> List[dict]:
        try:
            return OpenAIResponsesToolAdapter.to_tool_dicts(tools)
        except ValueError:
            return [
                tool.model_dump(mode="json") if hasattr(tool, "model_dump") else dict(tool)
                for tool in tools
            ]

    def _build_system_instructions(
        self,
        system_prompt_file: Optional[str],
        *,
        include_runtime_instructions: bool = True,
    ) -> str:
        prompt_file = system_prompt_file or self.cfg.system_prompt_file
        system_prompt_text = load_prompt(self.cfg.prompts_dir, prompt_file)
        if not include_runtime_instructions:
            return system_prompt_text
        return f"{system_prompt_text}\n\nRead only mode={self.cfg.read_only}. If something fails, explain why."

    def _build_client(self) -> OpenAI:
        return OpenAI(api_key=self.cfg.openai_api_key)

    def _format_error(self, exc: Exception) -> str:
        provider_message = self._provider_error_message(exc)
        if provider_message and "Error retrieving tool list from MCP server" in provider_message:
            return (
                f"{provider_message}. OpenAI could not list tools from the hosted MCP server; "
                "check the public MCP URL/server health or use an Agents SDK local MCP tool."
            )
        return provider_message or str(exc)

    def _provider_error_message(self, exc: Exception) -> Optional[str]:
        body = getattr(exc, "body", None)
        message = self._message_from_provider_body(body)
        if message:
            return message

        response = getattr(exc, "response", None)
        response_json = getattr(response, "json", None)
        if callable(response_json):
            try:
                return self._message_from_provider_body(response_json())
            except Exception:
                return None
        return None

    @staticmethod
    def _message_from_provider_body(body: Any) -> Optional[str]:
        if not isinstance(body, dict):
            return None
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)
        return None
