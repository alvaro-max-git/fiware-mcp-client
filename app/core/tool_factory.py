from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import MCPServerConfig, ToolDefinition, ToolsCatalog


class ToolFactory:
    """Builds concrete tool payloads from catalog definitions.

    For now only MCP tools are supported; additional tool types can be added
    incrementally without changing the consumer code.
    """

    def __init__(self, catalog: ToolsCatalog):
        self.catalog = catalog
        self._by_name: Dict[str, ToolDefinition] = {
            tool.name: tool for tool in catalog.tools_definitions
        }

    def build_tools(
        self, tool_names: List[str], overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List[dict]:
        tools: List[dict] = []
        for name in tool_names:
            definition = self._by_name.get(name)
            if not definition:
                raise ValueError(f"Tool '{name}' not found in catalog")
            override = overrides.get(name) if overrides else None
            tools.append(self._build_tool(definition, override))
        return tools

    def _build_tool(
        self, definition: ToolDefinition, override: Optional[Dict[str, Any]] = None
    ) -> dict:
        tool_type = definition.type.lower()
        config = self._merge_config(definition.config or {}, override)
        if tool_type == "mcp":
            return self._build_mcp_tool(definition, config)
        if tool_type == "openai-responses-tool":
            return self._build_openai_responses_tool(definition, config)
        if tool_type == "openai-agents-tool":
            return self._build_openai_agents_tool(definition, config)
        raise ValueError(f"Tool type '{definition.type}' is not supported yet")

    def _build_mcp_tool(self, definition: ToolDefinition, cfg: Dict[str, Any]) -> dict:
        url = cfg.get("url")
        if not url:
            raise ValueError(f"Tool '{definition.name}' is missing required 'url' in config")

        label = cfg.get("label") or definition.name
        allowed_raw = cfg.get("allowed_tools")
        if isinstance(allowed_raw, str):
            allowed = [t.strip() for t in allowed_raw.split(",") if t.strip()]
        else:
            allowed = list(allowed_raw) if allowed_raw else None

        server = MCPServerConfig(label=label, url=url, allowed_tools=allowed)
        return server.to_openai_tool()

    def _build_openai_responses_tool(
        self, definition: ToolDefinition, cfg: Dict[str, Any]
    ) -> dict:
        if "type" not in cfg:
            raise ValueError(
                f"Tool '{definition.name}' is missing required 'type' in config for openai-responses-tool"
            )
        return dict(cfg)

    def _build_openai_agents_tool(
        self, definition: ToolDefinition, cfg: Dict[str, Any]
    ) -> dict:
        if "type" not in cfg:
            raise ValueError(
                f"Tool '{definition.name}' is missing required 'type' in config for openai-agents-tool"
            )
        return dict(cfg)

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
