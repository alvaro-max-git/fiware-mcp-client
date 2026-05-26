from app.core.config import AppConfig
from app.core.types import RunRequest, RunResult
from app.services.chat_service import ChatService
from app.services.run_service import RunService


def test_chat_service_adds_default_session_id(monkeypatch):
    captured = {}

    def fake_run_turn(self, request):
        captured["session_id"] = request.session_id
        return RunResult(ok=True, output_text="ok", model_name="gpt-test")

    monkeypatch.setattr(RunService, "run_turn", fake_run_turn)

    result = ChatService(AppConfig()).run_turn(RunRequest(user_prompt="hello"))

    assert result.ok
    assert captured["session_id"] == ChatService.DEFAULT_SESSION_ID


def test_chat_service_streams_with_existing_session_id(monkeypatch):
    captured = {}

    def fake_stream_turn(self, request, *, on_text_delta):
        captured["session_id"] = request.session_id
        on_text_delta("hi")
        return RunResult(ok=True, output_text="hi", model_name="gpt-test")

    monkeypatch.setattr(RunService, "stream_turn", fake_stream_turn)
    chunks = []

    result = ChatService(AppConfig()).stream_turn(
        RunRequest(user_prompt="hello", session_id="course-demo"),
        on_text_delta=chunks.append,
    )

    assert result.output_text == "hi"
    assert chunks == ["hi"]
    assert captured["session_id"] == "course-demo"
