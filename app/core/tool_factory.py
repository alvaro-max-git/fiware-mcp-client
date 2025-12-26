from __future__ import annotations

from typing import Dict, List

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

    def build_tools(self, tool_names: List[str]) -> List[dict]:
        tools: List[dict] = []
        for name in tool_names:
            definition = self._by_name.get(name)
            if not definition:
                raise ValueError(f"Tool '{name}' not found in catalog")
            tools.append(self._build_tool(definition))
        return tools

    def _build_tool(self, definition: ToolDefinition) -> dict:
        tool_type = definition.type.lower()
        if tool_type == "mcp":
            return self._build_mcp_tool(definition)
        raise ValueError(f"Tool type '{definition.type}' is not supported yet")

    def _build_mcp_tool(self, definition: ToolDefinition) -> dict:
        cfg = definition.config or {}
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
