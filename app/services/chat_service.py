from __future__ import annotations

from typing import Callable

from app.core.config import AppConfig
from app.core.types import RunRequest, RunResult
from app.services.run_service import RunService


class ChatService:
    """Application service for persistent chat turns."""

    DEFAULT_SESSION_ID = "default"

    def __init__(self, cfg: AppConfig) -> None:
        self.run_service = RunService(cfg)

    def run_turn(self, request: RunRequest) -> RunResult:
        return self.run_service.run_turn(self._with_session_id(request))

    def stream_turn(
        self,
        request: RunRequest,
        *,
        on_text_delta: Callable[[str], None],
    ) -> RunResult:
        return self.run_service.stream_turn(
            self._with_session_id(request),
            on_text_delta=on_text_delta,
        )

    def _with_session_id(self, request: RunRequest) -> RunRequest:
        if request.session_id:
            return request
        return request.model_copy(update={"session_id": self.DEFAULT_SESSION_ID})
