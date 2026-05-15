from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

from app.core.config import (
    AppConfig,
    ClientConfig,
    MCPServerConfig,
    ProfilesConfig,
    ToolsCatalog,
)

_DOTENV_LOADED = False
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _load_dotenv_once() -> None:
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        load_dotenv()
        _DOTENV_LOADED = True


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


def load_app_config_from_env(*, require_mcp: bool = False) -> AppConfig:
    """Load legacy runtime configuration from environment variables."""

    _load_dotenv_once()
    defaults = AppConfig()
    api_key = os.getenv("OPENAI_API_KEY")
    mcp_map = load_mcp_servers_from_env()
    mcp_servers = list(mcp_map.values())

    eval_temp_env = os.getenv("EVAL_TEMPERATURE")
    eval_temperature = float(eval_temp_env) if eval_temp_env is not None else None

    cfg = AppConfig(
        openai_api_key=api_key,
        model=os.getenv("OPENAI_MODEL") or defaults.model,
        mcp_servers=mcp_servers,
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS") or defaults.max_output_tokens),
        read_only=os.getenv("READ_ONLY", "true").lower() in ("1", "true", "yes"),
        log_level=(os.getenv("LOG_LEVEL") or defaults.log_level).upper(),
        log_to_file=os.getenv("LOG_TO_FILE", "true").lower() in ("1", "true", "yes"),
        logs_dir=Path(os.getenv("LOGS_DIR") or defaults.logs_dir),
        prompts_dir=Path(os.getenv("PROMPTS_DIR") or defaults.prompts_dir),
        system_prompt_file=os.getenv("SYSTEM_PROMPT_FILE") or defaults.system_prompt_file,
        judge_model=os.getenv("EVAL_MODEL") or os.getenv("OPENAI_MODEL") or defaults.judge_model,
        judge_system_prompt_file=os.getenv("EVAL_SYSTEM_PROMPT_FILE")
        or defaults.judge_system_prompt_file,
        judge_temperature=eval_temperature,
    )
    cfg.validate(require_mcp=require_mcp)
    return cfg


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

    if client_cfg.model_name is not None:
        cfg.model = str(client_cfg.model_name)
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


def load_profiles_config(yaml_path: Path) -> ProfilesConfig:
    """Load agent profiles from a YAML file with sensible fallbacks."""

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
    """Parse MCP server definitions from env vars, compatible with legacy layout."""

    servers: Dict[str, MCPServerConfig] = {}
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
        servers[label] = MCPServerConfig(label=label, url=url, allowed_tools=allowed_list)
        i += 1

    if not servers:
        single_url = os.getenv("MCP_URL")
        single_label = os.getenv("MCP_LABEL", "fiware-mcp")
        single_allowed = os.getenv("MCP_ALLOWED_TOOLS")

        if single_url:
            allowed_list = [t.strip() for t in single_allowed.split(",")] if single_allowed else None
            servers[single_label] = MCPServerConfig(
                label=single_label,
                url=single_url,
                allowed_tools=allowed_list,
            )

    return servers


def load_client_config(yaml_path: Optional[Path] = None) -> ClientConfig:
    """Load config.yaml runtime configuration with env placeholder support."""

    _load_dotenv_once()

    candidates: List[Path] = []
    if yaml_path is not None:
        candidates.append(Path(yaml_path))
    else:
        candidates.append(Path("config.yaml"))

    expanded: List[Path] = []
    for candidate in candidates:
        expanded.append(candidate)
        if not candidate.is_absolute():
            expanded.append(Path.cwd() / candidate)

    for candidate in expanded:
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data = _resolve_env_placeholders(data)
            return ClientConfig(**data)

    searched = ", ".join(str(p) for p in expanded)
    raise FileNotFoundError(f"Client config not found. Tried: {searched}")
