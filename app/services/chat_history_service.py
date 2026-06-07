from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.api.schemas import ChatDetailResponse, ChatMessage, ChatSummary
from app.core.config import AgentProfile, ClientConfig, ProfilesConfig


class ChatHistoryUnsupported(RuntimeError):
    error = "chat_history_unsupported"

    def __init__(self, message: str = "No OpenAI Agents SQLite session profile is configured") -> None:
        super().__init__(message)
        self.message = message


class ChatNotFound(LookupError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Chat session '{session_id}' was not found")
        self.session_id = session_id


class ChatHistoryService:
    """Read and manage OpenAI Agents SDK SQLite chat history."""

    DEFAULT_DB_PATH = "data/sessions.sqlite"

    def __init__(self, client_cfg: ClientConfig, profiles: ProfilesConfig) -> None:
        self.db_path = _resolve_sqlite_session_path(client_cfg, profiles)

    def list_chats(self, *, limit: int = 50) -> list[ChatSummary]:
        if not self.db_path.exists() or not self._has_sdk_tables():
            return []

        safe_limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.created_at,
                    s.updated_at,
                    m.message_data,
                    m.created_at AS message_created_at
                FROM agent_sessions s
                LEFT JOIN agent_messages m ON m.session_id = s.session_id
                ORDER BY s.updated_at DESC, s.session_id ASC, m.id ASC
                """
            ).fetchall()

        summaries: list[ChatSummary] = []
        current_session_id: str | None = None
        current_rows: list[sqlite3.Row] = []

        def flush() -> None:
            if current_session_id is None or not current_rows:
                return
            summaries.append(_summary_from_rows(current_rows))

        for row in rows:
            session_id = str(row["session_id"])
            if current_session_id is None:
                current_session_id = session_id
            if session_id != current_session_id:
                flush()
                if len(summaries) >= safe_limit:
                    return summaries
                current_session_id = session_id
                current_rows = []
            current_rows.append(row)

        flush()
        return summaries[:safe_limit]

    def get_chat(self, session_id: str) -> ChatDetailResponse:
        if not self.db_path.exists() or not self._has_sdk_tables():
            raise ChatNotFound(session_id)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.created_at,
                    s.updated_at,
                    m.message_data,
                    m.created_at AS message_created_at
                FROM agent_sessions s
                LEFT JOIN agent_messages m ON m.session_id = s.session_id
                WHERE s.session_id = ?
                ORDER BY m.id ASC
                """,
                (session_id,),
            ).fetchall()

        if not rows:
            raise ChatNotFound(session_id)

        return ChatDetailResponse(
            session=_summary_from_rows(rows),
            messages=_messages_from_rows(rows),
        )

    def delete_chat(self, session_id: str) -> bool:
        if not self.db_path.exists() or not self._has_sdk_tables():
            return False

        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM agent_sessions WHERE session_id = ?", (session_id,))
            conn.commit()
        return True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _has_sdk_tables(self) -> bool:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name IN ('agent_sessions', 'agent_messages')
                """
            ).fetchall()
        return {str(row["name"]) for row in rows} == {"agent_sessions", "agent_messages"}


def _resolve_sqlite_session_path(client_cfg: ClientConfig, profiles: ProfilesConfig) -> Path:
    selected_id = client_cfg.agent_id or profiles.default_agent
    selected = _agent_by_id(profiles, selected_id)
    if selected is not None and _is_sqlite_session_agent(selected):
        return _session_db_path(selected)

    for agent in profiles.agents:
        if _is_sqlite_session_agent(agent):
            return _session_db_path(agent)

    raise ChatHistoryUnsupported()


def _agent_by_id(profiles: ProfilesConfig, agent_id: str | None) -> AgentProfile | None:
    if not agent_id:
        return None
    for agent in profiles.agents:
        if agent.id == agent_id:
            return agent
    return None


def _is_sqlite_session_agent(agent: AgentProfile) -> bool:
    if agent.backend.type != "openai_agents":
        return False
    session_cfg = agent.backend.session or {}
    if session_cfg.get("enabled") is False:
        return False
    provider = str(session_cfg.get("provider") or session_cfg.get("type") or "sqlite").lower()
    return provider == "sqlite"


def _session_db_path(agent: AgentProfile) -> Path:
    session_cfg = agent.backend.session or {}
    db_path = session_cfg.get("path") or session_cfg.get("db_path") or ChatHistoryService.DEFAULT_DB_PATH
    return Path(str(db_path))


def _summary_from_rows(rows: list[sqlite3.Row]) -> ChatSummary:
    first = rows[0]
    messages = _messages_from_rows(rows)
    title = _title_from_messages(messages)
    preview = messages[-1].content if messages else None
    return ChatSummary(
        session_id=str(first["session_id"]),
        title=title,
        created_at=_optional_str(first["created_at"]),
        updated_at=_optional_str(first["updated_at"]),
        message_count=len(messages),
        last_message_preview=_preview(preview),
    )


def _messages_from_rows(rows: list[sqlite3.Row]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for row in rows:
        raw_message = row["message_data"]
        if raw_message is None:
            continue
        for item in _sdk_items_from_json(raw_message):
            visible = _visible_message_from_sdk_item(item)
            if visible is None:
                continue
            role, content = visible
            messages.append(
                ChatMessage(
                    role=role,
                    content=content,
                    created_at=_optional_str(row["message_created_at"]),
                )
            )
    return messages


def _sdk_items_from_json(raw_message: Any) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(str(raw_message))
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _visible_message_from_sdk_item(item: dict[str, Any]) -> tuple[str, str] | None:
    role = item.get("role")
    if role not in {"user", "assistant"}:
        return None

    text = _text_from_content(item.get("content"))
    if not text:
        return None
    return role, text


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
            continue
        text = block.get("content")
        if isinstance(text, str):
            parts.append(text)

    return "\n".join(part for part in parts if part).strip()


def _title_from_messages(messages: list[ChatMessage]) -> str:
    for message in messages:
        if message.role == "user" and message.content:
            return _preview(message.content, limit=72) or "New chat"
    return "New chat"


def _preview(text: str | None, *, limit: int = 120) -> str | None:
    if text is None:
        return None
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None
