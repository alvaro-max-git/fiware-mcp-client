from __future__ import annotations

import json

import pytest
import requests

from app.ui.api_client import ApiClientError, FiwareApiClient
from app.ui.state import (
    agent_choices,
    empty_browser_state,
    new_session_id,
    save_session_messages,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload=None,
        lines=None,
    ):
        self.status_code = status_code
        self._payload = payload
        self._lines = lines or []
        self.closed = False

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def iter_lines(self, decode_unicode=False):
        yield from self._lines

    def raise_for_status(self):
        raise requests.HTTPError(f"{self.status_code} error")

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def test_health_calls_health_endpoint():
    session = FakeSession([FakeResponse(payload={"status": "ok"})])
    client = FiwareApiClient("http://api.test/api/v1", session=session)

    assert client.health() == {"status": "ok"}
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "http://api.test/api/v1/health"


def test_agents_returns_payload():
    payload = {
        "default_agent_id": "local",
        "agents": [{"id": "local", "supports_streaming": True}],
    }
    client = FiwareApiClient("http://api.test/api/v1", session=FakeSession([FakeResponse(payload=payload)]))

    assert client.agents()["default_agent_id"] == "local"


def test_chat_history_methods_call_expected_endpoints():
    session = FakeSession(
        [
            FakeResponse(payload={"chats": []}),
            FakeResponse(payload={"session": {"session_id": "sid"}, "messages": []}),
            FakeResponse(payload={"deleted": True, "session_id": "sid"}),
        ]
    )
    client = FiwareApiClient("http://api.test/api/v1", session=session)

    client.chats()
    client.chat_detail("sid")
    client.delete_chat("sid")

    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"].endswith("/chats")
    assert session.calls[1]["method"] == "GET"
    assert session.calls[1]["url"].endswith("/chats/sid")
    assert session.calls[2]["method"] == "DELETE"
    assert session.calls[2]["url"].endswith("/chats/sid")


def test_mcp_actions_post_expected_payloads():
    session = FakeSession(
        [
            FakeResponse(payload={"running": False}),
            FakeResponse(payload={"running": True}),
            FakeResponse(payload={"running": False}),
        ]
    )
    client = FiwareApiClient("http://api.test/api/v1", session=session)

    client.mcp_start(context_url="mcp-experiments")
    client.mcp_restart(context_url="context-data-loader")
    client.mcp_stop()

    assert session.calls[0]["url"].endswith("/mcp-server/start")
    assert session.calls[0]["json"] == {
        "host": "127.0.0.1",
        "port": 5001,
        "context_url": "mcp-experiments",
        "timeout_seconds": 10,
        "wait": True,
    }
    assert session.calls[1]["url"].endswith("/mcp-server/restart")
    assert session.calls[1]["json"]["context_url"] == "context-data-loader"
    assert session.calls[2]["url"].endswith("/mcp-server/stop")
    assert session.calls[2]["json"]["timeout_seconds"] == 5


def test_run_and_chat_send_turn_payloads():
    session = FakeSession(
        [
            FakeResponse(payload={"ok": True, "output_text": "run"}),
            FakeResponse(payload={"ok": True, "output_text": "chat"}),
        ]
    )
    client = FiwareApiClient("http://api.test/api/v1", session=session)

    client.run(
        prompt="List types",
        agent_id="agent-a",
        session_id="sid",
        max_output_tokens=123,
    )
    client.chat(
        prompt="Continue",
        agent_id="agent-a",
        session_id="sid",
        max_output_tokens=None,
    )

    assert session.calls[0]["url"].endswith("/run")
    assert session.calls[0]["json"] == {
        "prompt": "List types",
        "agent_id": "agent-a",
        "session_id": "sid",
        "max_output_tokens": 123,
    }
    assert session.calls[1]["url"].endswith("/chat")
    assert session.calls[1]["json"] == {
        "prompt": "Continue",
        "agent_id": "agent-a",
        "session_id": "sid",
    }


def test_chat_stream_parses_sse_events():
    response = FakeResponse(
        lines=[
            "event: delta",
            'data: {"type": "delta", "content": "Hel"}',
            "",
            "event: delta",
            'data: {"type": "delta", "content": "lo"}',
            "",
            "event: final",
            'data: {"type": "final", "result": {"ok": true, "output_text": "Hello"}}',
            "",
        ]
    )
    session = FakeSession([response])
    client = FiwareApiClient("http://api.test/api/v1", session=session)

    events = list(
        client.chat_stream(
            prompt="Hi",
            agent_id="local",
            session_id="sid",
            max_output_tokens=10,
        )
    )

    assert [event["type"] for event in events] == ["delta", "delta", "final"]
    assert events[0]["content"] == "Hel"
    assert events[-1]["result"]["output_text"] == "Hello"
    assert session.calls[0]["headers"] == {"Accept": "text/event-stream"}
    assert response.closed is True


def test_api_error_json_becomes_api_client_error():
    payload = {
        "error": "mcp_server_conflict",
        "message": "MCP server did not become reachable",
        "details": {"log_file": "logs/server.log"},
    }
    client = FiwareApiClient(
        "http://api.test/api/v1",
        session=FakeSession([FakeResponse(status_code=409, payload=payload)]),
    )

    with pytest.raises(ApiClientError) as exc_info:
        client.mcp_start(context_url="context-data-loader")

    assert exc_info.value.status_code == 409
    assert exc_info.value.error == "mcp_server_conflict"
    assert exc_info.value.details == {"log_file": "logs/server.log"}


def test_new_session_id_is_uuid():
    assert str(new_session_id())
    assert len(new_session_id()) == 36


def test_persisted_transcript_excludes_trace_and_raw_payloads():
    state = save_session_messages(
        empty_browser_state(),
        session_id="sid",
        selected_agent_id="local",
        messages=[
            {"role": "user", "content": "List types", "raw_response": {"secret": "x"}},
            {"role": "assistant", "content": "Type list", "mcp_trace": {"calls": []}},
        ],
    )

    serialized = json.dumps(state)
    assert "raw_response" not in serialized
    assert "mcp_trace" not in serialized
    assert state["sessions"]["sid"]["messages"] == [
        {"role": "user", "content": "List types"},
        {"role": "assistant", "content": "Type list"},
    ]


def test_agent_dropdown_choices_preserve_agent_ids():
    choices = agent_choices(
        [
            {"id": "fiware-client-agents-local", "model_name": "gpt-test", "supports_streaming": True},
            {"id": "fiware-client", "model_name": "gpt-basic", "supports_streaming": False},
        ]
    )

    assert choices[0] == ("fiware-client-agents-local - gpt-test - streaming", "fiware-client-agents-local")
    assert choices[1] == ("fiware-client - gpt-basic", "fiware-client")

