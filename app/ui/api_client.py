from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

import requests


class ApiClientError(Exception):
    """Small UI-facing error that hides transport stack details."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error: str = "api_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error = error
        self.details = details or {}


@dataclass
class FiwareApiClient:
    base_url: str
    timeout_seconds: float = 60.0
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def runtime(self) -> dict[str, Any]:
        return self._request("GET", "/runtime")

    def agents(self) -> dict[str, Any]:
        return self._request("GET", "/agents")

    def mcp_status(self) -> dict[str, Any]:
        return self._request("GET", "/mcp-server/status")

    def mcp_start(
        self,
        *,
        context_url: str,
        host: str = "127.0.0.1",
        port: int = 5001,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/mcp-server/start",
            json_payload={
                "host": host,
                "port": port,
                "context_url": context_url,
                "timeout_seconds": 10,
                "wait": True,
            },
        )

    def mcp_stop(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 5001,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/mcp-server/stop",
            json_payload={
                "host": host,
                "port": port,
                "timeout_seconds": 5,
            },
        )

    def mcp_restart(
        self,
        *,
        context_url: str,
        host: str = "127.0.0.1",
        port: int = 5001,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/mcp-server/restart",
            json_payload={
                "host": host,
                "port": port,
                "context_url": context_url,
                "timeout_seconds": 10,
            },
        )

    def run(
        self,
        *,
        prompt: str,
        agent_id: str | None,
        session_id: str | None,
        max_output_tokens: int | None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/run",
            json_payload=self._turn_payload(
                prompt=prompt,
                agent_id=agent_id,
                session_id=session_id,
                max_output_tokens=max_output_tokens,
            ),
        )

    def chat(
        self,
        *,
        prompt: str,
        agent_id: str | None,
        session_id: str,
        max_output_tokens: int | None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/chat",
            json_payload=self._turn_payload(
                prompt=prompt,
                agent_id=agent_id,
                session_id=session_id,
                max_output_tokens=max_output_tokens,
            ),
        )

    def chat_stream(
        self,
        *,
        prompt: str,
        agent_id: str | None,
        session_id: str,
        max_output_tokens: int | None,
    ) -> Iterator[dict[str, Any]]:
        response = self._open_stream(
            "/chat/stream",
            self._turn_payload(
                prompt=prompt,
                agent_id=agent_id,
                session_id=session_id,
                max_output_tokens=max_output_tokens,
            ),
        )
        try:
            yield from _iter_sse_json(response.iter_lines(decode_unicode=True))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _turn_payload(
        self,
        *,
        prompt: str,
        agent_id: str | None,
        session_id: str | None,
        max_output_tokens: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": prompt}
        if agent_id:
            payload["agent_id"] = agent_id
        if session_id:
            payload["session_id"] = session_id
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                self._url(path),
                json=json_payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise ApiClientError(
                f"Backend unavailable at {self.base_url}. Start FastAPI with uvicorn app.api.main:app.",
                error="request_failed",
            ) from exc

        self._raise_for_error_response(response)
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {"data": payload}

    def _open_stream(self, path: str, json_payload: dict[str, Any]) -> requests.Response:
        try:
            response = self.session.request(
                "POST",
                self._url(path),
                json=json_payload,
                timeout=self.timeout_seconds,
                stream=True,
                headers={"Accept": "text/event-stream"},
            )
        except requests.RequestException as exc:
            raise ApiClientError(
                f"Backend unavailable at {self.base_url}. Start FastAPI with uvicorn app.api.main:app.",
                error="request_failed",
            ) from exc

        self._raise_for_error_response(response)
        return response

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _raise_for_error_response(self, response: requests.Response) -> None:
        if response.status_code < 400:
            return

        payload: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            payload = {}

        if "message" in payload or "error" in payload:
            raise ApiClientError(
                str(payload.get("message") or payload.get("error") or "API request failed"),
                status_code=response.status_code,
                error=str(payload.get("error") or "api_error"),
                details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ApiClientError(
                str(exc),
                status_code=response.status_code,
                error="http_error",
            ) from exc


def _iter_sse_json(lines: Iterator[str | bytes]) -> Iterator[dict[str, Any]]:
    event: str | None = None
    data_lines: list[str] = []

    def flush() -> dict[str, Any] | None:
        if not data_lines:
            return None
        raw = "\n".join(data_lines)
        data_lines.clear()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiClientError(
                "Streaming response contained invalid JSON.",
                error="invalid_stream_event",
            ) from exc
        if isinstance(payload, dict):
            if event and "type" not in payload:
                payload["type"] = event
            return payload
        return {"type": event or "message", "data": payload}

    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.rstrip("\r")
        if line == "":
            payload = flush()
            if payload is not None:
                yield payload
            event = None
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())

    payload = flush()
    if payload is not None:
        yield payload
