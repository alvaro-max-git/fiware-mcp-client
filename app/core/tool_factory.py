from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional

from app.core.config import ToolDefinition, ToolsCatalog
from app.tools.specs import (
    FUNCTION_TOOL,
    MCP_HOSTED,
    MCP_LOCAL_TRANSPORTS,
    OPENAI_HOSTED_TOOL,
    ToolSpec,
    normalize_allowed_tools,
)


class ToolFactory:
    """Builds backend-neutral tool specs from catalog definitions.

    Backend-specific runtime objects are created by adapters in app.tools.
    """

    _TYPE_ALIASES = {
        "mcp": MCP_HOSTED,
        "openai-responses-tool": OPENAI_HOSTED_TOOL,
        "openai_responses_tool": OPENAI_HOSTED_TOOL,
        "openai-agents-tool": OPENAI_HOSTED_TOOL,
        "openai_agents_tool": OPENAI_HOSTED_TOOL,
    }

    def __init__(self, catalog: ToolsCatalog):
        self.catalog = catalog
        self._by_name: Dict[str, ToolDefinition] = {
            tool.name: tool for tool in catalog.tools_definitions
        }

    def build_tools(
        self, tool_names: List[str], overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List[ToolSpec]:
        tools: List[ToolSpec] = []
        for name in tool_names:
            definition = self._by_name.get(name)
            if not definition:
                raise ValueError(f"Tool '{name}' not found in catalog")
            override = overrides.get(name) if overrides else None
            tools.append(self._build_tool(definition, override))
        return tools

    def _build_tool(
        self, definition: ToolDefinition, override: Optional[Dict[str, Any]] = None
    ) -> ToolSpec:
        raw_type = definition.type.lower()
        tool_type = self._TYPE_ALIASES.get(raw_type, raw_type)
        config = self._merge_config(definition.config or {}, override)

        if raw_type == "mcp":
            warnings.warn(
                "Tool type 'mcp' is deprecated; use 'mcp_hosted' for Responses-hosted MCP tools.",
                DeprecationWarning,
                stacklevel=2,
            )

        if tool_type == MCP_HOSTED:
            return self._build_hosted_mcp_tool(definition, config)
        if tool_type in MCP_LOCAL_TRANSPORTS:
            return self._build_local_mcp_tool(definition, tool_type, config)
        if tool_type == OPENAI_HOSTED_TOOL:
            return self._build_openai_hosted_tool(definition, config)
        if tool_type == FUNCTION_TOOL:
            return ToolSpec(name=definition.name, type=tool_type, config=config)
        raise ValueError(f"Tool type '{definition.type}' is not supported yet")

    def _build_hosted_mcp_tool(self, definition: ToolDefinition, cfg: Dict[str, Any]) -> ToolSpec:
        url = cfg.get("server_url") or cfg.get("url")
        if not url:
            raise ValueError(
                f"Tool '{definition.name}' is missing required 'server_url' or 'url' in config"
            )

        normalized = dict(cfg)
        normalized["server_label"] = (
            normalized.get("server_label")
            or normalized.get("label")
            or normalized.get("name")
            or definition.name
        )
        normalized["server_url"] = url
        allowed_tools = normalize_allowed_tools(normalized.get("allowed_tools"))
        if allowed_tools:
            normalized["allowed_tools"] = allowed_tools
        normalized.setdefault("require_approval", "never")

        return ToolSpec(name=definition.name, type=MCP_HOSTED, config=normalized)

    def _build_local_mcp_tool(
        self, definition: ToolDefinition, tool_type: str, cfg: Dict[str, Any]
    ) -> ToolSpec:
        if tool_type in {"mcp_streamable_http", "mcp_sse"} and not (
            cfg.get("url") or cfg.get("server_url") or (cfg.get("params") or {}).get("url")
        ):
            raise ValueError(f"Tool '{definition.name}' is missing required 'url' in config")
        if tool_type == "mcp_stdio" and not (
            cfg.get("command") or (cfg.get("params") or {}).get("command")
        ):
            raise ValueError(f"Tool '{definition.name}' is missing required 'command' in config")

        normalized = dict(cfg)
        allowed_tools = normalize_allowed_tools(normalized.get("allowed_tools"))
        if allowed_tools:
            normalized["allowed_tools"] = allowed_tools
        return ToolSpec(name=definition.name, type=tool_type, config=normalized)

    def _build_openai_hosted_tool(
        self, definition: ToolDefinition, cfg: Dict[str, Any]
    ) -> ToolSpec:
        if "type" not in cfg:
            raise ValueError(
                f"Tool '{definition.name}' is missing required 'type' in config for openai hosted tool"
            )
        return ToolSpec(name=definition.name, type=OPENAI_HOSTED_TOOL, config=dict(cfg))

    def _merge_config(
        self, base: Dict[str, Any], override: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not override:
            return dict(base)
        merged: Dict[str, Any] = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._merge_config(merged.get(key, {}), value)
            else:
                merged[key] = value
        return merged
