from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import Depends

from app.core.config import (
    AppConfig,
    ClientConfig,
    ProfilesConfig,
    apply_client_config_overrides,
    load_client_config,
    load_profiles_config,
)
from app.core.mcp_launcher import MCPServerLauncher
from app.services.chat_history_service import ChatHistoryService, ChatHistoryUnsupported
from app.services.chat_service import ChatService
from app.services.run_service import RunService


BASE_URL = "/api/v1"
DEFAULT_PROFILES_YAML = "app/profiles/fiware-agents.yaml"
DEFAULT_TOOLS_YAML = "app/tools/tools.yaml"


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        error: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message
        self.details = details or {}


def get_client_config() -> ClientConfig:
    try:
        return load_client_config()
    except FileNotFoundError:
        return ClientConfig(
            profiles_yaml=DEFAULT_PROFILES_YAML,
            tools_yaml=DEFAULT_TOOLS_YAML,
        )
    except Exception as exc:
        raise ApiError(
            status_code=500,
            error="config_error",
            message=str(exc),
        ) from exc


def get_app_config(client_cfg: ClientConfig = Depends(get_client_config)) -> AppConfig:
    try:
        cfg = AppConfig.from_env(require_mcp=False)
        return apply_client_config_overrides(cfg, client_cfg)
    except Exception as exc:
        raise ApiError(
            status_code=500,
            error="config_error",
            message=str(exc),
        ) from exc


def get_run_service(cfg: AppConfig = Depends(get_app_config)) -> RunService:
    return RunService(cfg)


def get_chat_service(cfg: AppConfig = Depends(get_app_config)) -> ChatService:
    return ChatService(cfg)


def get_profiles_config(client_cfg: ClientConfig = Depends(get_client_config)) -> ProfilesConfig:
    if not client_cfg.profiles_yaml:
        raise ApiError(
            status_code=500,
            error="config_error",
            message="profiles_yaml is not configured",
        )
    try:
        return load_profiles_config(Path(client_cfg.profiles_yaml))
    except Exception as exc:
        raise ApiError(
            status_code=500,
            error="config_error",
            message=str(exc),
            details={"profiles_yaml": client_cfg.profiles_yaml},
        ) from exc


def get_chat_history_service(
    client_cfg: ClientConfig = Depends(get_client_config),
    profiles: ProfilesConfig = Depends(get_profiles_config),
) -> ChatHistoryService:
    try:
        return ChatHistoryService(client_cfg, profiles)
    except ChatHistoryUnsupported as exc:
        raise ApiError(
            status_code=400,
            error=exc.error,
            message=exc.message,
        ) from exc


def resolve_default_agent_id(
    client_cfg: ClientConfig,
    profiles: Optional[ProfilesConfig] = None,
) -> Optional[str]:
    if client_cfg.agent_id:
        return client_cfg.agent_id
    if profiles is not None:
        return profiles.default_agent
    if client_cfg.profiles_yaml:
        try:
            return load_profiles_config(Path(client_cfg.profiles_yaml)).default_agent
        except Exception:
            return None
    return None


LauncherFactory = Callable[[Dict[str, Any]], MCPServerLauncher]


def get_mcp_launcher_factory() -> LauncherFactory:
    return MCPServerLauncher.from_config

