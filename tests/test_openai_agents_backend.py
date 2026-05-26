from types import SimpleNamespace

from openai.types.responses import ResponseTextDeltaEvent

from app.backends.openai_agents_backend import OpenAIAgentsBackend
from app.tools.openai_agents_adapter import OpenAIAgentsToolAdapter, OpenAIAgentsToolRuntime
from app.tools.specs import MCP_STREAMABLE_HTTP, ToolSpec


def _fake_result(text: str = "done"):
    return SimpleNamespace(
        final_output=text,
        new_items=[],
        raw_responses=[],
        context_wrapper=SimpleNamespace(usage=None),
    )


def test_agents_backend_builds_sdk_agent_and_calls_runner_run(monkeypatch):
    from agents import Runner

    captured = {}

    async def fake_run(agent, input, **kwargs):
        captured["agent"] = agent
        captured["input"] = input
        captured["kwargs"] = kwargs
        return _fake_result()

    monkeypatch.setattr(Runner, "run", fake_run)

    backend = OpenAIAgentsBackend(
        model_name="gpt-test",
        api_key="test-key",
        temperature=0.2,
        max_output_tokens=123,
    )

    result = backend.generate(
        instructions="Use tools carefully.",
        user_prompt="Hello",
        tools=[],
        agent_name="fiware-client",
    )

    assert result.final_output == "done"
    assert captured["input"] == "Hello"
    assert captured["kwargs"]["max_turns"] == 10
    assert captured["agent"].name == "fiware-client"
    assert captured["agent"].model == "gpt-test"
    assert captured["agent"].model_settings.temperature == 0.2
    assert captured["agent"].model_settings.max_tokens == 123


def test_agents_backend_uses_sqlite_session_when_session_id_is_provided(tmp_path, monkeypatch):
    import agents
    from agents import Runner

    captured = {}

    class FakeSQLiteSession:
        def __init__(self, session_id, db_path=":memory:"):
            self.session_id = session_id
            self.db_path = db_path
            self.closed = False

        def close(self):
            self.closed = True

    async def fake_run(agent, input, **kwargs):
        captured["session"] = kwargs["session"]
        return _fake_result()

    monkeypatch.setattr(agents, "SQLiteSession", FakeSQLiteSession)
    monkeypatch.setattr(Runner, "run", fake_run)

    db_path = tmp_path / "sessions.sqlite"
    backend = OpenAIAgentsBackend(
        model_name="gpt-test",
        api_key="test-key",
        session_config={"enabled": True, "provider": "sqlite", "path": str(db_path)},
    )

    backend.generate(
        instructions="Remember context.",
        user_prompt="Hello",
        tools=[],
        session_id="chat-1",
    )

    session = captured["session"]
    assert session.session_id == "chat-1"
    assert session.db_path == str(db_path)
    assert session.closed


def test_agents_backend_enters_local_mcp_server_context(monkeypatch):
    from agents import Runner

    captured = {}

    class FakeMCPServer:
        entered = False
        exited = False

        async def __aenter__(self):
            self.entered = True
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self.exited = True

    server = FakeMCPServer()

    async def fake_run(agent, input, **kwargs):
        captured["mcp_servers"] = agent.mcp_servers
        return _fake_result()

    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(
        OpenAIAgentsToolAdapter,
        "to_runtime",
        lambda specs: OpenAIAgentsToolRuntime(mcp_servers=[server]),
    )

    backend = OpenAIAgentsBackend(
        model_name="gpt-test",
        api_key="test-key",
        session_config={"path": ":memory:"},
    )
    backend.generate(
        instructions="Use local MCP.",
        user_prompt="Hello",
        tools=[
            ToolSpec(
                name="fiware-local",
                type=MCP_STREAMABLE_HTTP,
                config={"url": "http://127.0.0.1:5001/mcp"},
            )
        ],
    )

    assert server.entered
    assert server.exited
    assert captured["mcp_servers"] == [server]


def test_agents_backend_streams_text_deltas(monkeypatch):
    from agents import Runner

    class FakeStreamingResult:
        final_output = "hello world"
        new_items = []
        raw_responses = []
        context_wrapper = SimpleNamespace(usage=None)

        async def stream_events(self):
            yield SimpleNamespace(
                type="raw_response_event",
                data=ResponseTextDeltaEvent(
                    content_index=0,
                    delta="hello ",
                    item_id="item-1",
                    logprobs=[],
                    output_index=0,
                    sequence_number=0,
                    type="response.output_text.delta",
                ),
            )
            yield SimpleNamespace(
                type="raw_response_event",
                data=ResponseTextDeltaEvent(
                    content_index=0,
                    delta="world",
                    item_id="item-1",
                    logprobs=[],
                    output_index=0,
                    sequence_number=1,
                    type="response.output_text.delta",
                ),
            )

    captured = {}

    def fake_run_streamed(agent, input, **kwargs):
        captured["agent"] = agent
        captured["input"] = input
        captured["kwargs"] = kwargs
        return FakeStreamingResult()

    monkeypatch.setattr(Runner, "run_streamed", fake_run_streamed)

    backend = OpenAIAgentsBackend(
        model_name="gpt-test",
        api_key="test-key",
        session_config={"path": ":memory:"},
    )
    chunks = []
    result = backend.stream(
        instructions="Stream.",
        user_prompt="Hello",
        tools=[],
        on_text_delta=chunks.append,
        session_id="chat-1",
    )

    assert result.final_output == "hello world"
    assert chunks == ["hello ", "world"]
    assert captured["input"] == "Hello"
    assert captured["kwargs"]["session"] is not None


def test_agents_backend_builds_configured_handoffs(monkeypatch):
    from agents import Runner
    from app.core.agent import Agent

    captured = {}

    async def fake_run(agent, input, **kwargs):
        captured["agent"] = agent
        return _fake_result()

    monkeypatch.setattr(Runner, "run", fake_run)

    handoff_backend = OpenAIAgentsBackend(model_name="gpt-handoff", api_key="test-key")
    handoff_agent = Agent(
        name="handoff-agent",
        system_prompt="Handle specialist work.",
        model_backend=handoff_backend,
    )
    backend = OpenAIAgentsBackend(model_name="gpt-main", api_key="test-key")

    backend.generate(
        instructions="Triage.",
        user_prompt="Hello",
        tools=[],
        handoff_agents=[handoff_agent],
    )

    assert len(captured["agent"].handoffs) == 1
    assert captured["agent"].handoffs[0].name == "handoff-agent"
    assert captured["agent"].handoffs[0].model == "gpt-handoff"
