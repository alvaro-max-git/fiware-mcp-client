from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any


BROWSER_STATE_KEY = "fiware-client-chat-state"
BROWSER_STATE_SECRET = "fiware-client-chat-state-v1"
STORAGE_VERSION = 1


def new_session_id() -> str:
    return str(uuid.uuid4())


def empty_browser_state() -> dict[str, Any]:
    return {
        "version": STORAGE_VERSION,
        "active_session_id": None,
        "selected_agent_id": None,
        "mode": "Chat",
        "stream": True,
        "sessions": {},
    }


def coerce_browser_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != STORAGE_VERSION:
        return empty_browser_state()

    state = copy.deepcopy(value)
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        state["sessions"] = {}
    state["mode"] = state.get("mode") if state.get("mode") in {"Chat", "Question"} else "Chat"
    state["stream"] = bool(state.get("stream", True))
    return state


def normalize_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []

    normalized: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or content is None:
            continue
        normalized.append({"role": role, "content": str(content)})
    return normalized


def ensure_active_session(
    browser_state: Any,
    *,
    selected_agent_id: str | None,
) -> tuple[dict[str, Any], str]:
    state = coerce_browser_state(browser_state)
    sessions = state.setdefault("sessions", {})
    session_id = state.get("active_session_id")
    if not session_id or session_id not in sessions:
        session_id = new_session_id()
        state["active_session_id"] = session_id
        sessions[session_id] = _session_record(session_id, selected_agent_id, [])
    return state, str(session_id)


def create_new_session(
    browser_state: Any,
    *,
    selected_agent_id: str | None,
) -> tuple[dict[str, Any], str]:
    state = coerce_browser_state(browser_state)
    session_id = new_session_id()
    state["active_session_id"] = session_id
    state["selected_agent_id"] = selected_agent_id
    state.setdefault("sessions", {})[session_id] = _session_record(
        session_id,
        selected_agent_id,
        [],
    )
    return state, session_id


def active_messages(browser_state: Any) -> list[dict[str, str]]:
    state = coerce_browser_state(browser_state)
    session_id = state.get("active_session_id")
    sessions = state.get("sessions", {})
    if not session_id or not isinstance(sessions, dict):
        return []
    session = sessions.get(session_id)
    if not isinstance(session, dict):
        return []
    return normalize_messages(session.get("messages"))


def save_session_messages(
    browser_state: Any,
    *,
    session_id: str,
    selected_agent_id: str | None,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    state = coerce_browser_state(browser_state)
    safe_messages = normalize_messages(messages)
    sessions = state.setdefault("sessions", {})
    existing = sessions.get(session_id) if isinstance(sessions.get(session_id), dict) else {}
    created_at = existing.get("created_at") or _now_iso()
    sessions[session_id] = {
        "session_id": session_id,
        "agent_id": selected_agent_id,
        "title": _title_from_messages(safe_messages),
        "messages": safe_messages,
        "created_at": created_at,
        "updated_at": _now_iso(),
    }
    state["active_session_id"] = session_id
    state["selected_agent_id"] = selected_agent_id
    return state


def update_browser_preferences(
    browser_state: Any,
    *,
    selected_agent_id: str | None = None,
    mode: str | None = None,
    stream: bool | None = None,
) -> dict[str, Any]:
    state = coerce_browser_state(browser_state)
    if selected_agent_id is not None:
        state["selected_agent_id"] = selected_agent_id
    if mode in {"Chat", "Question"}:
        state["mode"] = mode
    if stream is not None:
        state["stream"] = bool(stream)
    return state


def agent_choices(agents: list[dict[str, Any]]) -> list[tuple[str, str]]:
    choices = []
    for agent in agents:
        agent_id = str(agent.get("id") or "")
        if not agent_id:
            continue
        parts = [agent_id]
        model_name = agent.get("model_name")
        if model_name:
            parts.append(str(model_name))
        if agent.get("supports_streaming"):
            parts.append("streaming")
        choices.append((" - ".join(parts), agent_id))
    return choices


def choose_agent_id(
    agents: list[dict[str, Any]],
    *,
    stored_agent_id: str | None,
    default_agent_id: str | None,
) -> str | None:
    ids = [str(agent.get("id")) for agent in agents if agent.get("id")]
    if stored_agent_id in ids:
        return stored_agent_id
    if default_agent_id in ids:
        return default_agent_id
    return ids[0] if ids else None


def agent_supports_streaming(agents: list[dict[str, Any]], agent_id: str | None) -> bool:
    for agent in agents:
        if agent.get("id") == agent_id:
            return bool(agent.get("supports_streaming"))
    return False


def _session_record(
    session_id: str,
    selected_agent_id: str | None,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "session_id": session_id,
        "agent_id": selected_agent_id,
        "title": _title_from_messages(messages),
        "messages": messages,
        "created_at": now,
        "updated_at": now,
    }


def _title_from_messages(messages: list[dict[str, str]]) -> str:
    for message in messages:
        if message.get("role") == "user" and message.get("content"):
            title = " ".join(message["content"].split())
            return title[:72]
    return "New chat"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
