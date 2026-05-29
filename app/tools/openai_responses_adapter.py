from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Union

from app.tools.specs import (
    MCP_HOSTED,
    MCP_LOCAL_TRANSPORTS,
    OPENAI_HOSTED_TOOL,
    ToolSpec,
    normalize_allowed_tools,
)

ToolLike = Union[ToolSpec, Mapping[str, Any]]


class OpenAIResponsesToolAdapter:
    """Converts neutral tool specs into Responses API tool dictionaries."""

    @classmethod
    def to_tool_dicts(cls, specs: Iterable[ToolLike]) -> List[dict]:
        return [cls.to_tool_dict(spec) for spec in specs]

    @classmethod
    def to_tool_dict(cls, spec: ToolLike) -> dict:
        if isinstance(spec, Mapping):
            return dict(spec)

        if spec.type == MCP_HOSTED:
            return cls._hosted_mcp_to_dict(spec)

        if spec.type in MCP_LOCAL_TRANSPORTS:
            raise ValueError(
                f"Tool '{spec.name}' uses '{spec.type}', which is managed by the "
                "OpenAI Agents SDK and is not supported by the Responses backend"
            )

        if spec.type == OPENAI_HOSTED_TOOL:
            return cls._openai_hosted_tool_to_dict(spec)

        raise ValueError(f"Tool type '{spec.type}' is not supported by the Responses backend")

    @staticmethod
    def _hosted_mcp_to_dict(spec: ToolSpec) -> dict:
        cfg = spec.config
        server_label = cfg.get("server_label") or cfg.get("label") or cfg.get("name") or spec.name
        server_url = cfg.get("server_url") or cfg.get("url")
        if not server_url:
            raise ValueError(f"Tool '{spec.name}' is missing required 'server_url' or 'url'")

        tool: Dict[str, Any] = {
            "type": "mcp",
            "server_label": server_label,
            "server_url": server_url,
            "require_approval": cfg.get("require_approval", "never"),
        }
        allowed_tools = normalize_allowed_tools(cfg.get("allowed_tools"))
        if allowed_tools:
            tool["allowed_tools"] = allowed_tools
        if "headers" in cfg:
            tool["headers"] = cfg["headers"]
        return tool

    @staticmethod
    def _openai_hosted_tool_to_dict(spec: ToolSpec) -> dict:
        cfg = dict(spec.config)
        cfg.pop("provider", None)
        if "type" not in cfg:
            raise ValueError(
                f"Tool '{spec.name}' is missing required 'type' in config for openai hosted tool"
            )
        return cfg

