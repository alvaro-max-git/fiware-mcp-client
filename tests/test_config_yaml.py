import os
import textwrap
from pathlib import Path

import pytest

from app.core.config import (
    AppConfig,
    BackendConfig,
    apply_client_config_overrides,
    load_client_config,
    load_profiles_config,
)


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


def test_backend_config_accepts_model_name():
    cfg = BackendConfig(type="openai_responses", model_name="gpt-5")

    assert cfg.model_name == "gpt-5"
    assert cfg.model == "gpt-5"


def test_backend_config_accepts_legacy_model_alias():
    cfg = BackendConfig(type="openai_responses", model="gpt-5")

    assert cfg.model_name == "gpt-5"
    assert cfg.model == "gpt-5"


def test_backend_config_accepts_agents_session_config():
    cfg = BackendConfig(
        type="openai_agents",
        model_name="gpt-5",
        session={"enabled": True, "provider": "sqlite", "path": "data/sessions.sqlite"},
    )

    assert cfg.session["provider"] == "sqlite"


def test_profiles_yaml_accepts_legacy_model_alias(tmp_path: Path):
    profiles_yaml = tmp_path / "agents.yaml"
    profiles_yaml.write_text(
        textwrap.dedent(
            """
            default_agent: a
            agents:
              - id: a
                system_prompt: system.md
                backend:
                  type: openai_responses
                  model: gpt-5
            """
        ).strip(),
        encoding="utf-8",
    )

    cfg = load_profiles_config(profiles_yaml)

    assert cfg.agents[0].backend.model_name == "gpt-5"


def test_profiles_yaml_accepts_handoff_ids(tmp_path: Path):
    profiles_yaml = tmp_path / "agents.yaml"
    profiles_yaml.write_text(
        textwrap.dedent(
            """
            default_agent: triage
            agents:
              - id: triage
                system_prompt: triage.md
                handoffs: [specialist]
                backend:
                  type: openai_agents
                  model_name: gpt-5
              - id: specialist
                system_prompt: specialist.md
                backend:
                  type: openai_agents
                  model_name: gpt-5-mini
            """
        ).strip(),
        encoding="utf-8",
    )

    cfg = load_profiles_config(profiles_yaml)

    assert cfg.get_agent("triage").handoffs == ["specialist"]


def test_client_config_accepts_legacy_model_alias(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text("model: gpt-5-nano\n", encoding="utf-8")

    cfg = load_client_config(p)

    assert cfg.model_name == "gpt-5-nano"
    assert cfg.model == "gpt-5-nano"
