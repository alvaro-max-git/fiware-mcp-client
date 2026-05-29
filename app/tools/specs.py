from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


MCP_HOSTED = "mcp_hosted"
MCP_STREAMABLE_HTTP = "mcp_streamable_http"
MCP_SSE = "mcp_sse"
MCP_STDIO = "mcp_stdio"
OPENAI_HOSTED_TOOL = "openai_hosted_tool"
FUNCTION_TOOL = "function_tool"

MCP_LOCAL_TRANSPORTS = {MCP_STREAMABLE_HTTP, MCP_SSE, MCP_STDIO}


class ToolSpec(BaseModel):
    """Backend-neutral tool definition resolved from the YAML catalog."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)


def normalize_allowed_tools(value: Any) -> Optional[List[str]]:
    if isinstance(value, str):
        allowed = [tool.strip() for tool in value.split(",") if tool.strip()]
        return allowed or None
    if value:
        return [str(tool) for tool in value]
    return None

