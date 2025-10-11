from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from app.prompts import load_prompt

# Load environment variables from .env file
load_dotenv()

# MCP server configuration class
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
    #Model config
    openai_api_key: Optional[str] = field(default=None)
    model: str = field(default="gpt-4o-mini")
    max_output_tokens: int = field(default=800)

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

    #Load values from .env file
    @staticmethod
    def from_env() -> "AppConfig":

        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL")
        
        #Loads MCP servers, either with MCP_0, MCP_1 or without numbers: MCP_LABEL.
        mcp_servers: List[MCPServerConfig] = []
        i = 0
        while True:
            label = os.getenv(f"MCP{i}_LABEL")
            url = os.getenv(f"MCP{i}_URL")
            allowed = os.getenv(f"MCP{i}_ALLOWED_TOOLS")
            if not label and not url:
                break
            if not label or not url:
                raise ValueError(
                    f"Config MCP incompleta: faltan label o url para MCP{i} "
                    f"(MCP{i}_LABEL={label!r}, MCP{i}_URL={url!r})"
                )
            allowed_list = [t.strip() for t in allowed.split(",")] if allowed else None
            mcp_servers.append(MCPServerConfig(label=label, url=url, allowed_tools=allowed_list))
            i += 1

        if not mcp_servers:
            single_url = os.getenv("MCP_URL")
            single_label = os.getenv("MCP_LABEL", "fiware-mcp")
            single_allowed = os.getenv("MCP_ALLOWED_TOOLS")
            allowed_list = [t.strip() for t in single_allowed.split(",")] if single_allowed else None
            if single_url:
                mcp_servers.append(MCPServerConfig(label=single_label, url=single_url, allowed_tools=allowed_list))

        cfg = AppConfig(
            openai_api_key=api_key,
            model=model, # type: ignore
            mcp_servers=mcp_servers,
            max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "800")),
            read_only=os.getenv("READ_ONLY", "true").lower() in ("1", "true", "yes"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_to_file=os.getenv("LOG_TO_FILE", "true").lower() in ("1", "true", "yes"),
            logs_dir=Path(os.getenv("LOGS_DIR", "logs")),
            prompts_dir=Path(os.getenv("PROMPTS_DIR", "prompts")),
            system_prompt_file=os.getenv("SYSTEM_PROMPT_FILE", "system.md"),
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
        # ensure prompts dir exists (helps future prompt switching UX)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)

    def build_tools(self) -> List[dict]:
        """
        Returns OpenAI compatible tool list.
        """
        return [srv.to_openai_tool() for srv in self.mcp_servers]

    def load_system_prompt(self) -> str:
        return load_prompt(self.prompts_dir, self.system_prompt_file)





