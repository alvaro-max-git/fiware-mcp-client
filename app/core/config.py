from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

from app.prompts import load_prompt

_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        load_dotenv()
        _DOTENV_LOADED = True

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _replace_env_var(match: re.Match[str]) -> str:
    var_name = match.group(1)
    val = os.getenv(var_name)
    if val is None:
        raise ValueError(f"Environment variable '{var_name}' not set but required in config")
    return val


def _resolve_env_placeholders(value: Any) -> Any:
    """Recursively resolve ${VAR} placeholders using current environment."""

    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(_replace_env_var, value)
    if isinstance(value, list):
        return [_resolve_env_placeholders(v) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    return value

# ---------------------------------------------------------------------------
# 1. Legacy / Shared Configuration (Dataclasses)
# ---------------------------------------------------------------------------

@dataclass
class MCPServerConfig:
    label: str  # MCP server name. i.e. "fiware-mcp"
    url: str    # MCP server URL (public or local)
    allowed_tools: Optional[List[str]] = None

    def to_openai_tool(self) -> dict:
        d = {
            "type": "mcp",
            "server_label": self.label,
            "server_url": self.url,
            "require_approval": "never",  # TODO: define it as a .env variable
        }
        if self.allowed_tools:
            d["allowed_tools"] = self.allowed_tools # type: ignore
        return d

@dataclass
class AppConfig:
    """
    Legacy configuration container. 
    Used by the old runner.py and for global settings not yet migrated to YAML.
    """
    #Model config
    openai_api_key: Optional[str] = field(default=None)
    model: str = field(default="gpt-4o-mini")
    max_output_tokens: int = field(default=30000)

    mcp_servers: List[MCPServerConfig] = field(default_factory=list)
    
    #Security
    read_only: bool = field(default=True)

    #Logging
    log_level: str = field(default="INFO")  # "DEBUG"|"INFO"|"WARNING"|"ERROR"
    log_to_file: bool = field(default=True)
    logs_dir: Path = field(default=Path("logs"))

    # Prompts
    prompts_dir: Path = field(default=Path("prompts"))
    system_prompt_file: str = field(default="system1.md")

    #LLM-As-judge
    judge_model: str = field(default="gpt-4o-mini")
    judge_system_prompt_file: str = field(default="judge_system.md")
    judge_temperature: Optional[float] = field(default=None)

    #Load values from .env file
    @staticmethod
    def from_env(*, require_mcp: bool = False) -> "AppConfig":
        _load_dotenv_once()
        api_key = os.getenv("OPENAI_API_KEY")
        
        # Reuse the standalone function for MCP loading to avoid duplication
        mcp_map = load_mcp_servers_from_env()
        mcp_servers = list(mcp_map.values())

        # Parse temperature sólo si está definido en .env
        eval_temp_env = os.getenv("EVAL_TEMPERATURE")
        eval_temperature = float(eval_temp_env) if eval_temp_env is not None else None

        # The default values from the dataclass fields are used if os.getenv returns None
        cfg = AppConfig(
            openai_api_key=api_key,
            model=os.getenv("OPENAI_MODEL") or AppConfig.model,
            mcp_servers=mcp_servers,
            max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS") or AppConfig.max_output_tokens),
            read_only=os.getenv("READ_ONLY", "true").lower() in ("1", "true", "yes"),
            log_level=(os.getenv("LOG_LEVEL") or AppConfig.log_level).upper(),
            log_to_file=os.getenv("LOG_TO_FILE", "true").lower() in ("1", "true", "yes"),
            logs_dir=Path(os.getenv("LOGS_DIR") or AppConfig.logs_dir),
            prompts_dir=Path(os.getenv("PROMPTS_DIR") or AppConfig.prompts_dir),
            system_prompt_file=os.getenv("SYSTEM_PROMPT_FILE") or AppConfig.system_prompt_file,
            judge_model=os.getenv("EVAL_MODEL") or os.getenv("OPENAI_MODEL") or AppConfig.judge_model,
            judge_system_prompt_file=os.getenv("EVAL_SYSTEM_PROMPT_FILE") or AppConfig.judge_system_prompt_file,
            judge_temperature=eval_temperature,
        )
        cfg.validate(require_mcp=require_mcp)
        return cfg

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


# ---------------------------------------------------------------------------
# 2. New Pydantic-based config models (YAML-driven)
# ---------------------------------------------------------------------------

class BackendConfig(BaseModel):
    type: str = Field(..., description="Backend kind, e.g. openai_responses or openai_agent")
    model: str
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    base_url: Optional[str] = None
    client_options: Optional[Dict[str, str]] = None
    api_key: Optional[str] = None  # injected at runtime when possible


class AgentProfile(BaseModel):
    id: str
    system_prompt: str
    backend: BackendConfig
    description: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    mcp_servers: List[str] = Field(default_factory=list)


class ProfilesConfig(BaseModel):
    default_agent: str
    agents: List[AgentProfile] # type: ignore

    @model_validator(mode='before')
    def _ensure_default_exists(cls, values: Dict[str, object]) -> Dict[str, object]:
        default_agent = values.get("default_agent")
        agents = values.get("agents") or []
        if default_agent:
            def _agent_id(item: object) -> Optional[str]:
                if isinstance(item, dict):
                    return item.get("id")  # type: ignore[arg-type]
                return getattr(item, "id", None)

            if all(_agent_id(a) != default_agent for a in agents): # type: ignore[arg-type]
                raise ValueError(f"default_agent '{default_agent}' not found in agents list")
        return values

    @model_validator(mode="before")
    def _migrate_mcp_servers(cls, values: Dict[str, object]) -> Dict[str, object]:
        """Backward compatibility: if tools are missing, reuse mcp_servers."""

        if isinstance(values, dict):
            tools = values.get("tools")
            mcp_servers = values.get("mcp_servers")
            if (not tools or len(tools) == 0) and mcp_servers: # type: ignore
                values["tools"] = mcp_servers
        return values

    def get_agent(self, agent_id: str) -> AgentProfile: # type: ignore
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(f"Agent profile '{agent_id}' not found")


# ---------------------------------------------------------------------------
# 2.a Tool catalog config (YAML-driven)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 2.b Runtime client config (config.yaml)
# ---------------------------------------------------------------------------

class ClientConfig(BaseModel):
    """YAML-first runtime configuration.

    Secrets should be provided via environment variables and referenced via
    ${VAR} placeholders when needed.
    """

    # Session defaults
    profiles_yaml: Optional[str] = None
    tools_yaml: Optional[str] = None
    agent_id: Optional[str] = None

    # Legacy tools (MCP servers) for env-only mode
    mcp_servers: Optional[List[Dict[str, Any]]] = None

    # Runtime behavior
    read_only: Optional[bool] = None

    # Logging
    log_level: Optional[str] = None
    log_to_file: Optional[bool] = None
    logs_dir: Optional[str] = None

    # Prompts
    prompts_dir: Optional[str] = None
    system_prompt_file: Optional[str] = None  # legacy mode default

    # Legacy model defaults
    model: Optional[str] = None
    max_output_tokens: Optional[int] = None

    # Judge defaults
    judge_model: Optional[str] = None
    judge_system_prompt_file: Optional[str] = None
    judge_temperature: Optional[float] = None


def apply_client_config_overrides(cfg: AppConfig, client_cfg: ClientConfig) -> AppConfig:
    """Apply config.yaml overrides over the env-derived AppConfig."""

    if client_cfg.read_only is not None:
        cfg.read_only = bool(client_cfg.read_only)

    if client_cfg.log_level is not None:
        cfg.log_level = str(client_cfg.log_level).upper()
    if client_cfg.log_to_file is not None:
        cfg.log_to_file = bool(client_cfg.log_to_file)
    if client_cfg.logs_dir is not None:
        cfg.logs_dir = Path(str(client_cfg.logs_dir))

    if client_cfg.prompts_dir is not None:
        cfg.prompts_dir = Path(str(client_cfg.prompts_dir))
    if client_cfg.system_prompt_file is not None:
        cfg.system_prompt_file = str(client_cfg.system_prompt_file)

    if client_cfg.model is not None:
        cfg.model = str(client_cfg.model)
    if client_cfg.max_output_tokens is not None:
        cfg.max_output_tokens = int(client_cfg.max_output_tokens)

    if client_cfg.mcp_servers is not None:
        servers: List[MCPServerConfig] = []
        for item in client_cfg.mcp_servers:
            if not isinstance(item, dict):
                raise ValueError("config.yaml: 'mcp_servers' items must be mappings")
            label = item.get("label") or item.get("name")
            url = item.get("url")
            allowed_raw = item.get("allowed_tools")
            if not label or not url:
                raise ValueError("config.yaml: each mcp_servers item requires 'label' and 'url'")
            if isinstance(allowed_raw, str):
                allowed = [t.strip() for t in allowed_raw.split(",") if t.strip()]
            elif isinstance(allowed_raw, list):
                allowed = [str(t).strip() for t in allowed_raw if str(t).strip()]
            elif allowed_raw is None:
                allowed = None
            else:
                raise ValueError("config.yaml: 'allowed_tools' must be a string, list, or null")
            servers.append(MCPServerConfig(label=str(label), url=str(url), allowed_tools=allowed))
        cfg.mcp_servers = servers

    if client_cfg.judge_model is not None:
        cfg.judge_model = str(client_cfg.judge_model)
    if client_cfg.judge_system_prompt_file is not None:
        cfg.judge_system_prompt_file = str(client_cfg.judge_system_prompt_file)
    if client_cfg.judge_temperature is not None:
        cfg.judge_temperature = float(client_cfg.judge_temperature)

    return cfg


# ---------------------------------------------------------------------------
# 3. Helper Loaders
# ---------------------------------------------------------------------------

def load_profiles_config(yaml_path: Path) -> ProfilesConfig:
    """Load agent profiles from a YAML file with a couple of sensible fallbacks."""

    _load_dotenv_once()

    candidates = [yaml_path]
    if not yaml_path.is_absolute():
        candidates.append(Path.cwd() / yaml_path)
        candidates.append(Path("app/profiles") / yaml_path.name)

    for candidate in candidates:
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data = _resolve_env_placeholders(data)
            return ProfilesConfig(**data)

    searched = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"Profiles config not found. Tried: {searched}")


def load_tools_config(yaml_path: Path) -> ToolsCatalog:
    """Load tool catalog definitions from YAML with env placeholder support."""

    _load_dotenv_once()

    candidates = [yaml_path]
    if not yaml_path.is_absolute():
        candidates.append(Path.cwd() / yaml_path)
        candidates.append(Path("app/tools") / yaml_path.name)

    for candidate in candidates:
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data = _resolve_env_placeholders(data)
            return ToolsCatalog(**data)

    searched = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"Tools config not found. Tried: {searched}")


def load_mcp_servers_from_env() -> Dict[str, MCPServerConfig]:
    """Parse MCP server definitions from env vars (compatible with legacy layout)."""
    servers: Dict[str, MCPServerConfig] = {}
    i = 0
    
    # 1. Try numbered MCPs (MCP0_*, MCP1_*)
    while True:
        label = os.getenv(f"MCP{i}_LABEL")
        url = os.getenv(f"MCP{i}_URL")
        allowed = os.getenv(f"MCP{i}_ALLOWED_TOOLS")
        
        if not label and not url:
            break
        if not label or not url:
            # If one exists but not the other, it's a config error
            raise ValueError(
                f"Config MCP incompleta: faltan label o url para MCP{i} "
                f"(MCP{i}_LABEL={label!r}, MCP{i}_URL={url!r})"
            )
            
        allowed_list = [t.strip() for t in allowed.split(",")] if allowed else None
        servers[label] = MCPServerConfig(label=label, url=url, allowed_tools=allowed_list)
        i += 1

    # 2. Fallback: Try single MCP (MCP_*) if no numbered ones found OR just add to list
    # The legacy logic implies if we found numbered ones, we might still check the single one?
    # Usually it's either/or. Let's keep it additive but check for duplicates if needed.
    if not servers:
        single_url = os.getenv("MCP_URL")
        single_label = os.getenv("MCP_LABEL", "fiware-mcp")
        single_allowed = os.getenv("MCP_ALLOWED_TOOLS")
        
        if single_url:
            allowed_list = [t.strip() for t in single_allowed.split(",")] if single_allowed else None
            servers[single_label] = MCPServerConfig(label=single_label, url=single_url, allowed_tools=allowed_list)

    return servers


def load_client_config(yaml_path: Optional[Path] = None) -> ClientConfig:
    """Load config.yaml (runtime configuration) with env placeholder support.

    If yaml_path is None, it will try ./config.yaml.
    """

    _load_dotenv_once()

    candidates: List[Path] = []
    if yaml_path is not None:
        candidates.append(Path(yaml_path))
    else:
        candidates.append(Path("config.yaml"))

    # If relative, also try from CWD explicitly.
    expanded: List[Path] = []
    for c in candidates:
        expanded.append(c)
        if not c.is_absolute():
            expanded.append(Path.cwd() / c)

    for candidate in expanded:
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data = _resolve_env_placeholders(data)
            return ClientConfig(**data)

    searched = ", ".join(str(p) for p in expanded)
    raise FileNotFoundError(f"Client config not found. Tried: {searched}")





