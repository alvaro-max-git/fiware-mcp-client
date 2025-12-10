from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

from app.prompts import load_prompt

# Load environment variables from .env file
load_dotenv()

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
    def from_env() -> "AppConfig":
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
        cfg.validate()
        return cfg
    
    def validate(self) -> None:
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not defined. Review .env file")
        if not self.mcp_servers:
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

    def get_agent(self, agent_id: str) -> AgentProfile: # type: ignore
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(f"Agent profile '{agent_id}' not found")


# ---------------------------------------------------------------------------
# 3. Helper Loaders
# ---------------------------------------------------------------------------

def load_profiles_config(yaml_path: Path) -> ProfilesConfig:
    """Load agent profiles from a YAML file with a couple of sensible fallbacks."""

    candidates = [yaml_path]
    if not yaml_path.is_absolute():
        candidates.append(Path.cwd() / yaml_path)
        candidates.append(Path("app/profiles") / yaml_path.name)

    for candidate in candidates:
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return ProfilesConfig(**data)

    searched = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"Profiles config not found. Tried: {searched}")


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





