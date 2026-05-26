from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.tools.openai_responses_adapter import OpenAIResponsesToolAdapter
from app.tools.specs import (
    MCP_HOSTED,
    MCP_LOCAL_TRANSPORTS,
    MCP_SSE,
    MCP_STDIO,
    MCP_STREAMABLE_HTTP,
    ToolSpec,
    normalize_allowed_tools,
)


@dataclass
class OpenAIAgentsToolRuntime:
    """Runtime objects expected by the OpenAI Agents SDK."""

    tools: List[Any] = field(default_factory=list)
    mcp_servers: List[Any] = field(default_factory=list)


class OpenAIAgentsToolAdapter:
    """Converts neutral tool specs into Agents SDK hosted tools and MCP servers."""

    @classmethod
    def to_runtime(cls, specs: Iterable[ToolSpec]) -> OpenAIAgentsToolRuntime:
        runtime = OpenAIAgentsToolRuntime()
        for spec in specs:
            if spec.type == MCP_HOSTED:
                runtime.tools.append(cls._hosted_mcp_tool(spec))
            elif spec.type in MCP_LOCAL_TRANSPORTS:
                runtime.mcp_servers.append(cls._local_mcp_server(spec))
            else:
                raise ValueError(f"Tool type '{spec.type}' is not supported by the Agents adapter")
        return runtime

    @staticmethod
    def _hosted_mcp_tool(spec: ToolSpec) -> Any:
        from agents import HostedMCPTool

        tool_config = OpenAIResponsesToolAdapter.to_tool_dict(spec)
        return HostedMCPTool(tool_config=tool_config)

    @classmethod
    def _local_mcp_server(cls, spec: ToolSpec) -> Any:
        from agents.mcp import MCPServerSse, MCPServerStdio, MCPServerStreamableHttp

        server_cls = {
            MCP_STREAMABLE_HTTP: MCPServerStreamableHttp,
            MCP_SSE: MCPServerSse,
            MCP_STDIO: MCPServerStdio,
        }[spec.type]

        cfg = spec.config
        params = cls._local_mcp_params(spec)
        kwargs: Dict[str, Any] = {
            "params": params,
            "name": cfg.get("name") or cfg.get("server_label") or cfg.get("label") or spec.name,
            "cache_tools_list": bool(cfg.get("cache_tools_list", False)),
        }

        allowed_tools = normalize_allowed_tools(cfg.get("allowed_tools"))
        if allowed_tools:
            from agents.mcp import create_static_tool_filter

            kwargs["tool_filter"] = create_static_tool_filter(allowed_tool_names=allowed_tools)

        optional_fields = (
            "client_session_timeout_seconds",
            "use_structured_content",
            "max_retry_attempts",
            "retry_backoff_seconds_base",
            "require_approval",
        )
        supported_params = set(inspect.signature(server_cls).parameters)
        for field_name in optional_fields:
            if field_name in cfg and field_name in supported_params:
                kwargs[field_name] = cfg[field_name]

        return server_cls(**kwargs)

    @staticmethod
    def _local_mcp_params(spec: ToolSpec) -> Dict[str, Any]:
        cfg = spec.config
        params = dict(cfg.get("params") or {})

        if spec.type in {MCP_STREAMABLE_HTTP, MCP_SSE}:
            url = cfg.get("url") or cfg.get("server_url") or params.get("url")
            if not url:
                raise ValueError(f"Tool '{spec.name}' is missing required 'url' for {spec.type}")
            params["url"] = url
            for key in ("headers", "timeout"):
                if key in cfg:
                    params[key] = cfg[key]
            return params

        if spec.type == MCP_STDIO:
            command = cfg.get("command") or params.get("command")
            if not command:
                raise ValueError(f"Tool '{spec.name}' is missing required 'command' for mcp_stdio")
            params["command"] = command
            if "args" in cfg:
                params["args"] = cfg["args"]
            if "env" in cfg:
                params["env"] = cfg["env"]
            if "cwd" in cfg:
                params["cwd"] = cfg["cwd"]
            return params

        raise ValueError(f"Tool type '{spec.type}' is not a local MCP transport")

