import os
from pathlib import Path

import pytest

from app.core.config import AppConfig, apply_client_config_overrides, load_client_config


def test_load_client_config_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_client_config(tmp_path / "does-not-exist.yaml")


def test_load_client_config_env_placeholders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SOME_SECRET", "abc")
    p = tmp_path / "config.yaml"
    p.write_text(
        "profiles_yaml: ${SOME_SECRET}\n",
        encoding="utf-8",
    )

    cfg = load_client_config(p)
    assert cfg.profiles_yaml == "abc"


def test_load_client_config_env_placeholders_missing_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MISSING_ENV", raising=False)
    p = tmp_path / "config.yaml"
    p.write_text(
        "profiles_yaml: ${MISSING_ENV}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_client_config(p)


def test_config_yaml_mcp_servers_apply_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    p = tmp_path / "config.yaml"
    p.write_text(
        """
        mcp_servers:
          - label: fiware-mcp
            url: https://example.com/mcp
            allowed_tools: execute_query, get_entity_types
        """.strip(),
        encoding="utf-8",
    )

    client_cfg = load_client_config(p)
    cfg = AppConfig.from_env(require_mcp=False)
    cfg = apply_client_config_overrides(cfg, client_cfg)
    tools = cfg.build_tools()

    assert tools and tools[0]["type"] == "mcp"
    assert tools[0]["server_label"] == "fiware-mcp"
    assert tools[0]["server_url"] == "https://example.com/mcp"
    assert tools[0]["allowed_tools"] == ["execute_query", "get_entity_types"]
