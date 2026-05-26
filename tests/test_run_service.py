from pathlib import Path
from types import SimpleNamespace

from app.core.config import AppConfig
from app.core.types import RunRequest
from app.services.run_service import RunService


class _FakeResponses:
    def __init__(self) -> None:
        self.payload = None

    def create(self, **payload):
        self.payload = payload
        return SimpleNamespace(output_text='{"verdict": "pass"}', output=[], usage=None)


class _FakeClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


def test_run_service_legacy_no_tool_request_does_not_require_mcp(tmp_path: Path, monkeypatch):
    (tmp_path / "judge.md").write_text("Judge instructions", encoding="utf-8")
    cfg = AppConfig(
        openai_api_key="test-key",
        model="gpt-normal",
        judge_model="gpt-judge",
        prompts_dir=tmp_path,
        system_prompt_file="judge.md",
    )
    fake_client = _FakeClient()
    monkeypatch.setattr(RunService, "_build_client", lambda self: fake_client)

    result = RunService(cfg).run_turn(
        RunRequest(
            user_prompt="{}",
            model_name=cfg.judge_model,
            system_prompt_file="judge.md",
            use_tools=False,
        )
    )

    assert result.ok
    assert result.model_name == "gpt-judge"
    assert result.parsed_json == {"verdict": "pass"}
    assert "tools" not in fake_client.responses.payload


def test_run_service_can_skip_runtime_instruction_suffix(tmp_path: Path, monkeypatch):
    (tmp_path / "judge.md").write_text("Judge instructions", encoding="utf-8")
    cfg = AppConfig(openai_api_key="test-key", prompts_dir=tmp_path, system_prompt_file="judge.md")
    fake_client = _FakeClient()
    monkeypatch.setattr(RunService, "_build_client", lambda self: fake_client)

    RunService(cfg).run_turn(
        RunRequest(
            user_prompt="{}",
            system_prompt_file="judge.md",
            use_tools=False,
            include_runtime_instructions=False,
        )
    )

    assert fake_client.responses.payload["instructions"] == "Judge instructions"
