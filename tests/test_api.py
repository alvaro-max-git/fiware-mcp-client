import json
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_chat_service,
    get_client_config,
    get_mcp_launcher_factory,
    get_run_service,
)
from app.api.main import app
from app.core.config import AppConfig, ClientConfig
from app.core.mcp_launcher import MCPServerState
from app.core.types import RunResult
from app.services.chat_service import ChatService
from app.services.run_service import RunService


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _client() -> TestClient:
    return TestClient(app)


def _client_config() -> ClientConfig:
    return ClientConfig(
        profiles_yaml="app/profiles/fiware-agents.yaml",
        tools_yaml="app/tools/tools.yaml",
        agent_id="fiware-client-agents-local",
    )


def test_health_returns_ok():
    response = _client().get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "fiware-mcp-client"


def test_agents_serializes_profiles_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PROFILE_SECRET", "super-secret")
    profiles_yaml = tmp_path / "agents.yaml"
    profiles_yaml.write_text(
        textwrap.dedent(
            """
            default_agent: local
            agents:
              - id: local
                description: Local MCP agent
                system_prompt: system.md
                backend:
                  type: openai_agents
                  model_name: gpt-test
                  api_key: ${PROFILE_SECRET}
                  session:
                    enabled: true
                tools: [fiware-mcp-local]
              - id: one-shot
                description: Responses agent
                system_prompt: system.md
                backend:
                  type: openai_responses
                  model_name: gpt-responses
                tools: [fiware-mcp]
            """
        ).strip(),
        encoding="utf-8",
    )
    app.dependency_overrides[get_client_config] = lambda: ClientConfig(
        profiles_yaml=str(profiles_yaml),
        tools_yaml="app/tools/tools.yaml",
        agent_id="local",
    )

    response = _client().get("/api/v1/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_agent_id"] == "local"
    assert payload["agents"][0]["supports_sessions"] is True
    assert payload["agents"][0]["supports_streaming"] is True
    assert payload["agents"][1]["supports_sessions"] is False
    assert "super-secret" not in json.dumps(payload)
    assert "api_key" not in json.dumps(payload)


def test_run_maps_prompt_to_run_request_and_omits_raw_response():
    captured = {}

    class FakeRunService:
        def run_turn(self, request):
            captured["request"] = request
            return RunResult(
                ok=True,
                output_text="done",
                raw_response={"provider": "object"},
                model_name="gpt-test",
                metadata={
                    "tools": [{"name": "fiware-mcp"}],
                    "mcp_trace": {
                        "calls": [{"tool": "execute_query"}],
                        "call_count": 1,
                        "queries": ["/ngsi-ld/v1/types"],
                        "usage": {"input_tokens": 3},
                    },
                },
            )

    app.dependency_overrides[get_client_config] = _client_config
    app.dependency_overrides[get_run_service] = lambda: FakeRunService()

    response = _client().post(
        "/api/v1/run",
        json={"prompt": "  List available entity types  ", "max_output_tokens": 123},
    )

    assert response.status_code == 200
    request = captured["request"]
    assert request.user_prompt == "List available entity types"
    assert request.profiles_yaml == "app/profiles/fiware-agents.yaml"
    assert request.tools_yaml == "app/tools/tools.yaml"
    assert request.agent_id == "fiware-client-agents-local"
    assert request.max_output_tokens == 123
    payload = response.json()
    assert payload["mcp_trace"]["call_count"] == 1
    assert payload["metadata"] == {"tools": [{"name": "fiware-mcp"}]}
    assert "raw_response" not in payload


def test_provider_error_result_stays_http_200():
    class FakeRunService:
        def run_turn(self, request):
            return RunResult(
                ok=False,
                output_text="",
                model_name="gpt-test",
                error="provider failed",
            )

    app.dependency_overrides[get_client_config] = _client_config
    app.dependency_overrides[get_run_service] = lambda: FakeRunService()

    response = _client().post("/api/v1/run", json={"prompt": "hello"})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "provider failed"


def test_chat_applies_default_session_when_omitted(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_run_turn(self, request):
        captured["session_id"] = request.session_id
        return RunResult(ok=True, output_text="ok", model_name="gpt-test")

    monkeypatch.setattr(RunService, "run_turn", fake_run_turn)
    app.dependency_overrides[get_client_config] = _client_config
    app.dependency_overrides[get_chat_service] = lambda: ChatService(AppConfig(openai_api_key="test"))

    response = _client().post("/api/v1/chat", json={"prompt": "hello"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["session_id"] == ChatService.DEFAULT_SESSION_ID


def test_chat_stream_emits_delta_and_final_events():
    class FakeChatService:
        def stream_turn(self, request, *, on_text_delta):
            on_text_delta("Checking")
            on_text_delta(" the Context Broker")
            return RunResult(ok=True, output_text="done", model_name="gpt-test")

    app.dependency_overrides[get_client_config] = _client_config
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService()

    response = _client().post("/api/v1/chat/stream", json={"prompt": "hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert 'event: delta\ndata: {"type": "delta", "content": "Checking"}' in body
    assert 'event: final\ndata: {"type": "final", "result":' in body
    assert '"output_text": "done"' in body


def test_mcp_server_endpoints_call_launcher_and_serialize_state(tmp_path: Path):
    actions = []

    state = MCPServerState(
        running=True,
        reachable=True,
        managed=True,
        endpoint="http://127.0.0.1:5001/mcp",
        pid=12345,
        pid_file=tmp_path / "server.pid",
        log_file=tmp_path / "server.log",
        message="running",
    )

    class FakeLauncher:
        def __init__(self, config):
            self.config = config

        def status(self):
            actions.append(("status", self.config))
            return state

        def start(self, *, timeout_seconds, wait=True):
            actions.append(("start", self.config, timeout_seconds, wait))
            return state

        def stop(self, *, timeout_seconds):
            actions.append(("stop", self.config, timeout_seconds))
            return state

        def restart(self, *, timeout_seconds):
            actions.append(("restart", self.config, timeout_seconds))
            return state

    app.dependency_overrides[get_mcp_launcher_factory] = lambda: FakeLauncher
    client = _client()

    status_response = client.get("/api/v1/mcp-server/status")
    start_response = client.post(
        "/api/v1/mcp-server/start",
        json={
            "host": "127.0.0.1",
            "port": 5101,
            "context_url": "mcp-experiments",
            "write_mode": True,
            "timeout_seconds": 2,
            "wait": False,
        },
    )
    stop_response = client.post(
        "/api/v1/mcp-server/stop",
        json={"host": "127.0.0.1", "port": 5101, "timeout_seconds": 1},
    )
    restart_response = client.post(
        "/api/v1/mcp-server/restart",
        json={
            "host": "127.0.0.1",
            "port": 5102,
            "context_url": "context-data-loader",
            "write_mode": True,
            "timeout_seconds": 3,
        },
    )

    assert status_response.status_code == 200
    assert status_response.json()["pid_file"].endswith("server.pid")
    assert start_response.status_code == 200
    assert stop_response.status_code == 200
    assert restart_response.status_code == 200
    assert actions[0][0] == "status"
    assert actions[1] == (
        "start",
        {
            "host": "127.0.0.1",
            "port": 5101,
            "context_url": "mcp-experiments",
            "write_mode": True,
        },
        2,
        False,
    )
    assert actions[2] == (
        "stop",
        {
            "host": "127.0.0.1",
            "port": 5101,
            "context_url": "context-data-loader",
            "write_mode": False,
        },
        1,
    )
    assert actions[3] == (
        "restart",
        {
            "host": "127.0.0.1",
            "port": 5102,
            "context_url": "context-data-loader",
            "write_mode": True,
        },
        3,
    )

