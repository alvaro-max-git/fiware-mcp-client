from __future__ import annotations

from app.core.config import AppConfig
from app.core.normalizers import extract_mcp_trace_from_response
from app.core.types import RunRequest, RunResult
from app.services.run_service import RunService


def run_turn(cfg: AppConfig, req: RunRequest) -> RunResult:
    """Compatibility wrapper around the Phase 2 application service."""

    return RunService(cfg).run_turn(req)


def run_once(cfg: AppConfig, req: RunRequest) -> RunResult:
    """Compatibility wrapper for older callers during migration."""

    return run_turn(cfg, req)


_extract_mcp_trace_from_response = extract_mcp_trace_from_response
