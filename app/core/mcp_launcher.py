from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


MANAGED_LAUNCHER_NAMES = {"fiware-mcp-server", "fiware_mcp_server", "fiware"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass
class MCPServerState:
    running: bool
    reachable: bool
    managed: bool
    endpoint: str
    pid: Optional[int] = None
    pid_file: Optional[Path] = None
    log_file: Optional[Path] = None
    message: str = ""


class MCPServerLauncher:
    """Launch and manage the bundled FIWARE MCP server over local HTTP."""

    def __init__(
        self,
        *,
        python_executable: Optional[str] = None,
        server_dir: Optional[Path] = None,
        script_path: Optional[Path] = None,
        host: str = "127.0.0.1",
        port: int = 5001,
        context_url: str = "context-data-loader",
        pid_file: Optional[Path] = None,
        log_file: Optional[Path] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> None:
        root = repo_root()
        self.python_executable = python_executable or sys.executable
        self.server_dir = self._resolve_path(server_dir or Path("fiware-mcp-server"), root)
        self.script_path = self._resolve_path(script_path or self.server_dir / "server.py", root)
        self.host = host
        self.port = int(port)
        self.context_url = context_url
        self.pid_file = self._resolve_path(pid_file or Path("data/fiware-mcp-server.pid"), root)
        self.log_file = self._resolve_path(log_file or Path("logs/fiware-mcp-server.log"), root)
        self.extra_env = dict(extra_env or {})

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]] = None) -> "MCPServerLauncher":
        cfg = dict(config or {})
        return cls(
            python_executable=cfg.get("python") or cfg.get("python_executable"),
            server_dir=Path(cfg["server_dir"]) if cfg.get("server_dir") else None,
            script_path=Path(cfg["script_path"]) if cfg.get("script_path") else None,
            host=str(cfg.get("host") or "127.0.0.1"),
            port=int(cfg.get("port") or 5001),
            context_url=str(cfg.get("context_url") or cfg.get("context-url") or "context-data-loader"),
            pid_file=Path(cfg["pid_file"]) if cfg.get("pid_file") else None,
            log_file=Path(cfg["log_file"]) if cfg.get("log_file") else None,
            extra_env={str(k): str(v) for k, v in dict(cfg.get("env") or {}).items()},
        )

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"

    def http_command(self) -> List[str]:
        return [
            self.python_executable,
            str(self.script_path),
            "--http",
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--context-url",
            self.context_url,
        ]

    def stdio_command(self) -> List[str]:
        return [
            self.python_executable,
            str(self.script_path),
            "--context-url",
            self.context_url,
        ]

    def status(self) -> MCPServerState:
        pid = self._read_pid()
        managed = self._pid_is_alive(pid) if pid is not None else False
        reachable = self._is_reachable()
        running = managed or reachable
        message = "running" if running else "stopped"
        if reachable and not managed:
            message = "endpoint reachable, but no managed PID was found"
        if managed and not reachable:
            message = "managed process found, but HTTP endpoint is not reachable yet"
        return MCPServerState(
            running=running,
            reachable=reachable,
            managed=managed,
            endpoint=self.endpoint,
            pid=pid if managed else None,
            pid_file=self.pid_file,
            log_file=self.log_file,
            message=message,
        )

    def ensure_running(self, *, timeout_seconds: float = 10.0) -> MCPServerState:
        state = self.status()
        if state.running:
            return state
        return self.start(timeout_seconds=timeout_seconds)

    def start(self, *, timeout_seconds: float = 10.0, wait: bool = True) -> MCPServerState:
        state = self.status()
        if state.running:
            return state

        if not self.script_path.exists():
            raise FileNotFoundError(f"FIWARE MCP server script not found: {self.script_path}")

        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(self.extra_env)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        with open(self.log_file, "ab") as log:
            process = subprocess.Popen(
                self.http_command(),
                cwd=str(self.server_dir),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=creationflags,
            )

        self._write_pid(process.pid)

        if wait:
            ready = self.wait_until_ready(timeout_seconds=timeout_seconds, process=process)
            if not ready:
                exit_code = process.poll()
                if exit_code is not None:
                    self._clear_pid()
                    raise RuntimeError(
                        "FIWARE MCP server exited before becoming reachable "
                        f"(exit code {exit_code}). See log: {self.log_file}"
                    )
                raise TimeoutError(
                    "FIWARE MCP server did not become reachable at "
                    f"{self.endpoint} within {timeout_seconds:g}s. See log: {self.log_file}"
                )

        return self.status()

    def stop(self, *, timeout_seconds: float = 5.0) -> MCPServerState:
        pid = self._read_pid()
        if pid is None:
            return self.status()
        if not self._pid_is_alive(pid):
            self._clear_pid()
            return self.status()

        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self._pid_is_alive(pid):
                self._clear_pid()
                return self.status()
            time.sleep(0.1)

        if hasattr(signal, "SIGKILL"):
            os.kill(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGTERM)
        self._clear_pid()
        return self.status()

    def restart(self, *, timeout_seconds: float = 10.0) -> MCPServerState:
        self.stop()
        return self.start(timeout_seconds=timeout_seconds)

    def wait_until_ready(
        self,
        *,
        timeout_seconds: float = 10.0,
        process: Optional[subprocess.Popen[Any]] = None,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                return False
            if self._is_reachable():
                return True
            time.sleep(0.1)
        return False

    def _is_reachable(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=0.25):
                return True
        except OSError:
            return False

    def _read_pid(self) -> Optional[int]:
        try:
            raw = self.pid_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _write_pid(self, pid: int) -> None:
        self.pid_file.write_text(str(pid), encoding="utf-8")

    def _clear_pid(self) -> None:
        try:
            self.pid_file.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _pid_is_alive(pid: Optional[int]) -> bool:
        if pid is None or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _resolve_path(path: Path, root: Path) -> Path:
        path = Path(path)
        return path if path.is_absolute() else root / path


def resolve_managed_tool_config(tool_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Fill local MCP transport details from the bundled server launcher config."""

    launcher_name = config.get("launcher") or config.get("managed_by")
    if not launcher_name:
        return dict(config)
    if str(launcher_name) not in MANAGED_LAUNCHER_NAMES:
        return dict(config)

    resolved = dict(config)
    launcher = MCPServerLauncher.from_config(resolved)

    if tool_type == "mcp_stdio":
        command = launcher.stdio_command()
        resolved["command"] = command[0]
        resolved["args"] = command[1:]
        resolved["cwd"] = str(launcher.server_dir)
        return resolved

    if tool_type in {"mcp_streamable_http", "mcp_sse"}:
        auto_start = bool(resolved.get("auto_start", True))
        timeout = float(resolved.get("startup_timeout_seconds", 10.0))
        state = launcher.ensure_running(timeout_seconds=timeout) if auto_start else launcher.status()
        resolved.setdefault("url", state.endpoint)
        resolved.setdefault("server_url", state.endpoint)
        return resolved

    return resolved
