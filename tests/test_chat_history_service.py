from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.core.config import ClientConfig, ProfilesConfig
from app.services.chat_history_service import ChatHistoryService, ChatHistoryUnsupported


def _profiles(db_path: Path, *, default_agent: str = "responses") -> ProfilesConfig:
    return ProfilesConfig(
        default_agent=default_agent,
        agents=[
            {
                "id": "responses",
                "system_prompt": "system.md",
                "backend": {"type": "openai_responses", "model_name": "gpt-test"},
            },
            {
                "id": "agents",
                "system_prompt": "system.md",
                "backend": {
                    "type": "openai_agents",
                    "model_name": "gpt-test",
                    "session": {"enabled": True, "provider": "sqlite", "path": str(db_path)},
                },
            },
        ],
    )


def _unsupported_profiles() -> ProfilesConfig:
    return ProfilesConfig(
        default_agent="responses",
        agents=[
            {
                "id": "responses",
                "system_prompt": "system.md",
                "backend": {"type": "openai_responses", "model_name": "gpt-test"},
            }
        ],
    )


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


def _insert_session(
    path: Path,
    session_id: str,
    *,
    created_at: str,
    updated_at: str,
    messages: list[tuple[dict, str]],
) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO agent_sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, created_at, updated_at),
        )
        for payload, message_created_at in messages:
            conn.execute(
                "INSERT INTO agent_messages (session_id, message_data, created_at) VALUES (?, ?, ?)",
                (session_id, json.dumps(payload), message_created_at),
            )


def test_lists_sessions_sorted_newest_and_derives_summary(tmp_path: Path):
    db_path = tmp_path / "sessions.sqlite"
    _create_sdk_db(db_path)
    _insert_session(
        db_path,
        "old",
        created_at="2026-06-01 10:00:00",
        updated_at="2026-06-01 10:02:00",
        messages=[({"role": "user", "content": "Old question"}, "2026-06-01 10:01:00")],
    )
    _insert_session(
        db_path,
        "new",
        created_at="2026-06-02 10:00:00",
        updated_at="2026-06-02 10:03:00",
        messages=[
            ({"role": "user", "content": "List entity types"}, "2026-06-02 10:01:00"),
            ({"role": "assistant", "content": "There are three types."}, "2026-06-02 10:02:00"),
        ],
    )
    service = ChatHistoryService(ClientConfig(), _profiles(db_path))

    summaries = service.list_chats()

    assert [summary.session_id for summary in summaries] == ["new", "old"]
    assert summaries[0].title == "List entity types"
    assert summaries[0].message_count == 2
    assert summaries[0].last_message_preview == "There are three types."


def test_returns_visible_user_and_assistant_messages_only(tmp_path: Path):
    db_path = tmp_path / "sessions.sqlite"
    _create_sdk_db(db_path)
    _insert_session(
        db_path,
        "chat-1",
        created_at="2026-06-01 10:00:00",
        updated_at="2026-06-01 10:04:00",
        messages=[
            ({"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}, "2026-06-01 10:01:00"),
            ({"type": "reasoning", "summary": []}, "2026-06-01 10:02:00"),
            ({"type": "function_call", "name": "execute_query"}, "2026-06-01 10:03:00"),
            (
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hi there"}],
                },
                "2026-06-01 10:04:00",
            ),
        ],
    )
    service = ChatHistoryService(ClientConfig(agent_id="agents"), _profiles(db_path))

    detail = service.get_chat("chat-1")

    assert [(message.role, message.content) for message in detail.messages] == [
        ("user", "Hello"),
        ("assistant", "Hi there"),
    ]
    assert detail.session.message_count == 2


def test_delete_removes_session_and_messages(tmp_path: Path):
    db_path = tmp_path / "sessions.sqlite"
    _create_sdk_db(db_path)
    _insert_session(
        db_path,
        "chat-1",
        created_at="2026-06-01 10:00:00",
        updated_at="2026-06-01 10:01:00",
        messages=[({"role": "user", "content": "Delete me"}, "2026-06-01 10:01:00")],
    )
    service = ChatHistoryService(ClientConfig(), _profiles(db_path))

    assert service.delete_chat("chat-1") is True

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_messages").fetchone()[0] == 0


def test_unsupported_config_raises_stable_error():
    with pytest.raises(ChatHistoryUnsupported) as exc_info:
        ChatHistoryService(ClientConfig(), _unsupported_profiles())

    assert exc_info.value.error == "chat_history_unsupported"
