from __future__ import annotations

import json
import sqlite3
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_client_config
from app.api.main import app
from app.core.config import ClientConfig


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _client() -> TestClient:
    return TestClient(app)


def _create_sdk_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE agent_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                message_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "INSERT INTO agent_sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            ("chat-1", "2026-06-01 10:00:00", "2026-06-01 10:03:00"),
        )
        conn.execute(
            "INSERT INTO agent_messages (session_id, message_data, created_at) VALUES (?, ?, ?)",
            (
                "chat-1",
                json.dumps({"role": "user", "content": "List buildings"}),
                "2026-06-01 10:01:00",
            ),
        )
        conn.execute(
            "INSERT INTO agent_messages (session_id, message_data, created_at) VALUES (?, ?, ?)",
            (
                "chat-1",
                json.dumps({"role": "assistant", "content": "Building A"}),
                "2026-06-01 10:02:00",
            ),
        )


def _profiles_yaml(tmp_path: Path, db_path: Path) -> Path:
    profiles_yaml = tmp_path / "agents.yaml"
    profiles_yaml.write_text(
        textwrap.dedent(
            f"""
            default_agent: responses
            agents:
              - id: responses
                system_prompt: system.md
                backend:
                  type: openai_responses
                  model_name: gpt-test
              - id: agents
                system_prompt: system.md
                backend:
                  type: openai_agents
                  model_name: gpt-test
                  session:
                    enabled: true
                    provider: sqlite
                    path: "{db_path.as_posix()}"
            """
        ).strip(),
        encoding="utf-8",
    )
    return profiles_yaml


def test_chat_history_endpoints_list_detail_and_delete(tmp_path: Path):
    db_path = tmp_path / "sessions.sqlite"
    _create_sdk_db(db_path)
    profiles_yaml = _profiles_yaml(tmp_path, db_path)
    app.dependency_overrides[get_client_config] = lambda: ClientConfig(
        profiles_yaml=str(profiles_yaml),
        tools_yaml="app/tools/tools.yaml",
    )
    client = _client()

    list_response = client.get("/api/v1/chats")
    detail_response = client.get("/api/v1/chats/chat-1")
    delete_response = client.delete("/api/v1/chats/chat-1")
    list_after_delete = client.get("/api/v1/chats")

    assert list_response.status_code == 200
    assert list_response.json()["chats"][0]["title"] == "List buildings"
    assert detail_response.status_code == 200
    assert detail_response.json()["messages"] == [
        {"role": "user", "content": "List buildings", "created_at": "2026-06-01 10:01:00"},
        {"role": "assistant", "content": "Building A", "created_at": "2026-06-01 10:02:00"},
    ]
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "session_id": "chat-1"}
    assert list_after_delete.json()["chats"] == []


def test_chat_detail_returns_404_for_missing_session(tmp_path: Path):
    db_path = tmp_path / "sessions.sqlite"
    _create_sdk_db(db_path)
    profiles_yaml = _profiles_yaml(tmp_path, db_path)
    app.dependency_overrides[get_client_config] = lambda: ClientConfig(
        profiles_yaml=str(profiles_yaml),
        tools_yaml="app/tools/tools.yaml",
    )

    response = _client().get("/api/v1/chats/missing")

    assert response.status_code == 404
    assert response.json()["error"] == "chat_not_found"


def test_chat_history_unsupported_returns_stable_error(tmp_path: Path):
    profiles_yaml = tmp_path / "agents.yaml"
    profiles_yaml.write_text(
        textwrap.dedent(
            """
            default_agent: responses
            agents:
              - id: responses
                system_prompt: system.md
                backend:
                  type: openai_responses
                  model_name: gpt-test
            """
        ).strip(),
        encoding="utf-8",
    )
    app.dependency_overrides[get_client_config] = lambda: ClientConfig(
        profiles_yaml=str(profiles_yaml),
        tools_yaml="app/tools/tools.yaml",
    )

    response = _client().get("/api/v1/chats")

    assert response.status_code == 400
    assert response.json()["error"] == "chat_history_unsupported"
