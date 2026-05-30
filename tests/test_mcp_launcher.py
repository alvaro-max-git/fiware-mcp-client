from pathlib import Path

from app.core.mcp_launcher import MCPServerLauncher, resolve_managed_tool_config


def test_launcher_builds_default_endpoint():
    launcher = MCPServerLauncher(host="127.0.0.1", port=5101)

    assert launcher.endpoint == "http://127.0.0.1:5101/mcp"
    assert "--http" in launcher.http_command()
    assert "--context-url" in launcher.stdio_command()


def test_resolve_managed_stdio_tool_config_points_to_bundled_server():
    resolved = resolve_managed_tool_config(
        "mcp_stdio",
        {
            "launcher": "fiware-mcp-server",
            "context_url": "mcp-experiments",
        },
    )

    assert resolved["command"]
    assert "server.py" in resolved["args"][0]
    assert "--context-url" in resolved["args"]
    assert "mcp-experiments" in resolved["args"]
    assert resolved["cwd"].endswith("fiware-mcp-server")


def test_resolve_managed_http_tool_config_can_skip_auto_start():
    resolved = resolve_managed_tool_config(
        "mcp_streamable_http",
        {
            "launcher": "fiware-mcp-server",
            "host": "127.0.0.1",
            "port": 5102,
            "auto_start": False,
        },
    )

    assert resolved["url"] == "http://127.0.0.1:5102/mcp"
    assert resolved["server_url"] == "http://127.0.0.1:5102/mcp"


def test_launcher_status_uses_pid_file(tmp_path: Path):
    pid_file = tmp_path / "server.pid"
    log_file = tmp_path / "server.log"
    launcher = MCPServerLauncher(pid_file=pid_file, log_file=log_file, port=5103)

    state = launcher.status()

    assert not state.running
    assert state.pid_file == pid_file
    assert state.log_file == log_file


def test_pid_liveness_handles_windows_system_error(monkeypatch):
    def raise_system_error(pid, signal_number):
        raise SystemError("invalid pid check")

    monkeypatch.setattr("app.core.mcp_launcher.os.kill", raise_system_error)

    assert MCPServerLauncher._pid_is_alive(12345) is False
