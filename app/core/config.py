from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.core.model_name import ModelName
from app.prompts import load_prompt


@dataclass
class MCPServerConfig:
    label: str
    url: str
    allowed_tools: Optional[List[str]] = None

    def to_openai_tool(self) -> dict:
        d = {
            "type": "mcp",
            "server_label": self.label,
            "server_url": self.url,
            "require_approval": "never",
        }
        if self.allowed_tools:
            d["allowed_tools"] = self.allowed_tools
        return d


@dataclass
class AppConfig:
    """Legacy runtime configuration container.

    Loading from environment and YAML lives in app.core.config_loader. The
    from_env classmethod remains as a compatibility entry point for current
    CLI, benchmark, and eval code.
    """

    openai_api_key: Optional[str] = field(default=None)
    model: ModelName = field(default="gpt-4o-mini")
    max_output_tokens: int = field(default=200000)

    mcp_servers: List[MCPServerConfig] = field(default_factory=list)

    read_only: bool = field(default=True)

    log_level: str = field(default="INFO")
    log_to_file: bool = field(default=True)
    logs_dir: Path = field(default=Path("logs"))

    prompts_dir: Path = field(default=Path("prompts"))
    system_prompt_file: str = field(default="system1.md")

    judge_model: ModelName = field(default="gpt-4o-mini")
    judge_system_prompt_file: str = field(default="judge_system.md")
    judge_temperature: Optional[float] = field(default=None)

    @staticmethod
    def from_env(*, require_mcp: bool = False) -> "AppConfig":
        from app.core.config_loader import load_app_config_from_env

        return load_app_config_from_env(require_mcp=require_mcp)

    def validate(self, *, require_mcp: bool = True) -> None:
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not defined. Review .env file")
        if require_mcp and not self.mcp_servers:
            raise ValueError("At least one MCP Server must be defined")
        if self.max_output_tokens <= 0:
            raise ValueError("MAX_OUTPUT_TOKENS must be > 0.")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("LOG_LEVEL must be DEBUG|INFO|WARNING|ERROR.")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)

    def build_tools(self) -> List[dict]:
        return [srv.to_openai_tool() for srv in self.mcp_servers]

    def load_system_prompt(self) -> str:
        return load_prompt(self.prompts_dir, self.system_prompt_file)

    def load_judge_prompt(self) -> str:
        return load_prompt(self.prompts_dir, self.judge_system_prompt_file)


class BackendConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(..., description="Backend kind, e.g. openai_responses or openai_agents")
    model_name: ModelName = Field(
        validation_alias=AliasChoices("model_name", "model"),
        description="Provider model identifier. The legacy YAML key 'model' is accepted.",
    )
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    base_url: Optional[str] = None
    client_options: Optional[Dict[str, Any]] = None
    session: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None

    @property
    def model(self) -> str:
        """Deprecated compatibility accessor for Phase 1 callers."""

        return self.model_name


class AgentProfile(BaseModel):
    id: str
    system_prompt: str
    backend: BackendConfig
    description: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    tool_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    mcp_servers: List[str] = Field(default_factory=list)
    handoffs: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_mcp_servers(cls, values: Dict[str, object]) -> Dict[str, object]:
        if isinstance(values, dict):
            tools = values.get("tools")
            mcp_servers = values.get("mcp_servers")
            if (not tools or len(tools) == 0) and mcp_servers:  # type: ignore[arg-type]
                values["tools"] = mcp_servers
        return values


class ProfilesConfig(BaseModel):
    default_agent: str
    agents: List[AgentProfile]

    @model_validator(mode="before")
    @classmethod
    def _ensure_default_exists(cls, values: Dict[str, object]) -> Dict[str, object]:
        default_agent = values.get("default_agent")
        agents = values.get("agents") or []
        if default_agent:
            def _agent_id(item: object) -> Optional[str]:
                if isinstance(item, dict):
                    return item.get("id")  # type: ignore[arg-type]
                return getattr(item, "id", None)

            if all(_agent_id(a) != default_agent for a in agents):  # type: ignore[arg-type]
                raise ValueError(f"default_agent '{default_agent}' not found in agents list")
        return values

    def get_agent(self, agent_id: str) -> AgentProfile:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(f"Agent profile '{agent_id}' not found")


class ToolDefinition(BaseModel):
    name: str
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class ToolsCatalog(BaseModel):
    tools_definitions: List[ToolDefinition] = Field(default_factory=list)

    def get(self, name: str) -> ToolDefinition:
        for tool in self.tools_definitions:
            if tool.name == name:
                return tool
        raise KeyError(f"Tool '{name}' not found in catalog")


class ClientConfig(BaseModel):
    """YAML-first runtime configuration.

    Secrets should be provided via environment variables and referenced via
    ${VAR} placeholders when needed.
    """

    model_config = ConfigDict(populate_by_name=True)

    profiles_yaml: Optional[str] = None
    tools_yaml: Optional[str] = None
    agent_id: Optional[str] = None

    mcp_servers: Optional[List[Dict[str, Any]]] = None

    read_only: Optional[bool] = None

    log_level: Optional[str] = None
    log_to_file: Optional[bool] = None
    logs_dir: Optional[str] = None

    prompts_dir: Optional[str] = None
    system_prompt_file: Optional[str] = None

    model_name: Optional[ModelName] = Field(
        default=None,
        validation_alias=AliasChoices("model_name", "model"),
        description="Legacy-mode default model. The legacy YAML key 'model' is accepted.",
    )
    max_output_tokens: Optional[int] = None

    judge_model: Optional[ModelName] = None
    judge_system_prompt_file: Optional[str] = None
    judge_temperature: Optional[float] = None

    @property
    def model(self) -> Optional[str]:
        """Deprecated compatibility accessor for existing override code."""

        return self.model_name


def apply_client_config_overrides(cfg: AppConfig, client_cfg: ClientConfig) -> AppConfig:
    from app.core.config_loader import apply_client_config_overrides as _apply

    return _apply(cfg, client_cfg)


def load_client_config(yaml_path: Optional[Path] = None) -> ClientConfig:
    from app.core.config_loader import load_client_config as _load

    return _load(yaml_path)


def load_mcp_servers_from_env() -> Dict[str, MCPServerConfig]:
    from app.core.config_loader import load_mcp_servers_from_env as _load

    return _load()


def load_profiles_config(yaml_path: Path) -> ProfilesConfig:
    from app.core.config_loader import load_profiles_config as _load

    return _load(yaml_path)


def load_tools_config(yaml_path: Path) -> ToolsCatalog:
    from app.core.config_loader import load_tools_config as _load

    return _load(yaml_path)
