from app.cli import build_parser, cmd_bench
from app.core.config import AppConfig
from app.services.chat_service import ChatService


def test_chat_parser_defaults_to_persistent_session_id():
    args = build_parser().parse_args(["chat", "--prompt", "hello"])

    assert args.cmd == "chat"
    assert args.prompt == "hello"
    assert args.session_id == ChatService.DEFAULT_SESSION_ID
    assert not args.stream


def test_bench_permission_error_is_user_friendly(monkeypatch, capsys):
    def raise_permission(*args, **kwargs):
        raise PermissionError(13, "Permission denied", "locked.csv")

    monkeypatch.setattr("app.cli.run_benchmark", raise_permission)
    args = build_parser().parse_args(["bench", "--csv", "input.csv", "--out", "locked.csv"])

    assert cmd_bench(AppConfig(openai_api_key="test"), args) == 1
    assert "Cannot write benchmark output" in capsys.readouterr().out
