from app.cli import build_parser
from app.services.chat_service import ChatService


def test_chat_parser_defaults_to_persistent_session_id():
    args = build_parser().parse_args(["chat", "--prompt", "hello"])

    assert args.cmd == "chat"
    assert args.prompt == "hello"
    assert args.session_id == ChatService.DEFAULT_SESSION_ID
    assert not args.stream
