from __future__ import annotations

import json
from importlib import metadata
from queue import Queue
from threading import Thread
from typing import Any, Dict, Generator

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import (
    BASE_URL,
    DEFAULT_PROFILES_YAML,
    DEFAULT_TOOLS_YAML,
    ApiError,
    LauncherFactory,
    get_chat_service,
    get_chat_history_service,
    get_client_config,
    get_mcp_launcher_factory,
    get_profiles_config,
    get_run_service,
    resolve_default_agent_id,
)
from app.api.schemas import (
    AgentInfo,
    AgentsResponse,
    ChatDetailResponse,
    ChatsListResponse,
    DeleteChatResponse,
    ErrorResponse,
    HealthResponse,
    MCPServerRestartRequest,
    MCPServerStartRequest,
    MCPServerStateResponse,
    MCPServerStopRequest,
    PromptTurnRequest,
    RunResponse,
    RuntimeFeatures,
    RuntimeResponse,
)
from app.core.config import ClientConfig, ProfilesConfig
from app.core.mcp_launcher import MCPServerState
from app.core.types import RunRequest, RunResult
from app.services.chat_history_service import ChatHistoryService, ChatNotFound
from app.services.chat_service import ChatService
from app.services.run_service import RunService


def _package_version() -> str:
    try:
        return metadata.version("fiware-mcp-client")
    except metadata.PackageNotFoundError:
        return "0.1.0"


app = FastAPI(
    title="FIWARE MCP Client API",
    version=_package_version(),
)
router = APIRouter(prefix=BASE_URL)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    payload = ErrorResponse(
        error=exc.error,
        message=exc.message,
        details=exc.details,
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))


def _error_response(status_code: int = 500) -> Dict[int | str, Dict[str, Any]]:
    return {status_code: {"model": ErrorResponse}}


def _request_from_body(body: PromptTurnRequest, client_cfg: ClientConfig) -> RunRequest:
    return RunRequest(
        user_prompt=body.prompt,
        profiles_yaml=client_cfg.profiles_yaml,
        tools_yaml=client_cfg.tools_yaml,
        agent_id=body.agent_id or client_cfg.agent_id,
        session_id=body.session_id,
        max_output_tokens=body.max_output_tokens,
    )


def _safe_service_error(exc: Exception, *, error: str) -> ApiError:
    return ApiError(
        status_code=500,
        error=error,
        message=str(exc),
    )


def _mcp_launcher_from_config(
    factory: LauncherFactory,
    *,
    host: str = "127.0.0.1",
    port: int = 5001,
    context_url: str = "context-data-loader",
    write_mode: bool = False,
):
    return factory(
        {
            "host": host,
            "port": port,
            "context_url": context_url,
            "write_mode": write_mode,
        }
    )


def _mcp_conflict_error(exc: Exception) -> ApiError:
    return ApiError(
        status_code=409,
        error="mcp_server_conflict",
        message=str(exc),
    )


def _state_response(state: MCPServerState) -> MCPServerStateResponse:
    return MCPServerStateResponse.from_state(state)


def _sse(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chat_stream_events(
    service: ChatService,
    request: RunRequest,
) -> Generator[str, None, None]:
    events: Queue[tuple[str, Any]] = Queue()

    def run_stream() -> None:
        try:
            result = service.stream_turn(
                request,
                on_text_delta=lambda delta: events.put(("delta", delta)),
            )
            events.put(("final", result))
        except Exception as exc:
            events.put(("error", exc))
        finally:
            events.put(("done", None))

    Thread(target=run_stream, daemon=True).start()

    while True:
        event_type, payload = events.get()
        if event_type == "done":
            break
        if event_type == "delta":
            yield _sse("delta", {"type": "delta", "content": str(payload)})
            continue
        if event_type == "final":
            result = RunResponse.from_result(payload).model_dump(mode="json")
            yield _sse("final", {"type": "final", "result": result})
            continue
        if event_type == "error":
            yield _sse(
                "error",
                {
                    "type": "error",
                    "error": "stream_failed",
                    "message": str(payload),
                },
            )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="fiware-mcp-client",
        version=_package_version(),
    )


@router.get(
    "/runtime",
    response_model=RuntimeResponse,
    responses=_error_response(),
)
def runtime(client_cfg: ClientConfig = Depends(get_client_config)) -> RuntimeResponse:
    return RuntimeResponse(
        base_url=BASE_URL,
        read_only=client_cfg.read_only if client_cfg.read_only is not None else True,
        default_agent_id=resolve_default_agent_id(client_cfg),
        profiles_yaml=client_cfg.profiles_yaml or DEFAULT_PROFILES_YAML,
        tools_yaml=client_cfg.tools_yaml or DEFAULT_TOOLS_YAML,
        features=RuntimeFeatures(),
    )


@router.get(
    "/agents",
    response_model=AgentsResponse,
    responses=_error_response(),
)
def agents(
    client_cfg: ClientConfig = Depends(get_client_config),
    profiles: ProfilesConfig = Depends(get_profiles_config),
) -> AgentsResponse:
    agents_response = []
    for agent in profiles.agents:
        backend_type = agent.backend.type
        session_cfg = agent.backend.session or {}
        supports_sessions = backend_type == "openai_agents" and session_cfg.get("enabled") is not False
        agents_response.append(
            AgentInfo(
                id=agent.id,
                description=agent.description,
                backend_type=backend_type,
                model_name=str(agent.backend.model_name),
                tools=list(agent.tools),
                supports_sessions=supports_sessions,
                supports_streaming=backend_type == "openai_agents",
            )
        )

    return AgentsResponse(
        default_agent_id=resolve_default_agent_id(client_cfg, profiles) or profiles.default_agent,
        agents=agents_response,
    )


@router.post(
    "/run",
    response_model=RunResponse,
    responses=_error_response(),
)
def run_turn(
    body: PromptTurnRequest,
    client_cfg: ClientConfig = Depends(get_client_config),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    try:
        result = service.run_turn(_request_from_body(body, client_cfg))
    except Exception as exc:
        raise _safe_service_error(exc, error="run_failed") from exc
    return RunResponse.from_result(result)


@router.post(
    "/chat",
    response_model=RunResponse,
    responses=_error_response(),
)
def chat_turn(
    body: PromptTurnRequest,
    client_cfg: ClientConfig = Depends(get_client_config),
    service: ChatService = Depends(get_chat_service),
) -> RunResponse:
    try:
        result = service.run_turn(_request_from_body(body, client_cfg))
    except Exception as exc:
        raise _safe_service_error(exc, error="chat_failed") from exc
    return RunResponse.from_result(result)


@router.post(
    "/chat/stream",
    responses={
        200: {"content": {"text/event-stream": {}}},
        500: {"model": ErrorResponse},
    },
)
def chat_stream(
    body: PromptTurnRequest,
    client_cfg: ClientConfig = Depends(get_client_config),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    request = _request_from_body(body, client_cfg)
    return StreamingResponse(
        _chat_stream_events(service, request),
        media_type="text/event-stream",
    )


@router.get(
    "/chats",
    response_model=ChatsListResponse,
    responses=_error_response(400),
)
def list_chats(
    limit: int = Query(default=50, gt=0, le=200),
    service: ChatHistoryService = Depends(get_chat_history_service),
) -> ChatsListResponse:
    return ChatsListResponse(chats=service.list_chats(limit=limit))


@router.get(
    "/chats/{session_id}",
    response_model=ChatDetailResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_chat(
    session_id: str,
    service: ChatHistoryService = Depends(get_chat_history_service),
) -> ChatDetailResponse:
    try:
        return service.get_chat(session_id)
    except ChatNotFound as exc:
        raise ApiError(
            status_code=404,
            error="chat_not_found",
            message=str(exc),
            details={"session_id": session_id},
        ) from exc


@router.delete(
    "/chats/{session_id}",
    response_model=DeleteChatResponse,
    responses=_error_response(400),
)
def delete_chat(
    session_id: str,
    service: ChatHistoryService = Depends(get_chat_history_service),
) -> DeleteChatResponse:
    service.delete_chat(session_id)
    return DeleteChatResponse(deleted=True, session_id=session_id)


@router.get(
    "/mcp-server/status",
    response_model=MCPServerStateResponse,
    responses=_error_response(),
)
def mcp_server_status(
    factory: LauncherFactory = Depends(get_mcp_launcher_factory),
) -> MCPServerStateResponse:
    try:
        launcher = _mcp_launcher_from_config(factory)
        return _state_response(launcher.status())
    except Exception as exc:
        raise _safe_service_error(exc, error="mcp_server_error") from exc


@router.post(
    "/mcp-server/start",
    response_model=MCPServerStateResponse,
    responses={409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def mcp_server_start(
    body: MCPServerStartRequest | None = None,
    factory: LauncherFactory = Depends(get_mcp_launcher_factory),
) -> MCPServerStateResponse:
    body = body or MCPServerStartRequest()
    try:
        launcher = _mcp_launcher_from_config(
            factory,
            host=body.host,
            port=body.port,
            context_url=body.context_url,
            write_mode=body.write_mode,
        )
        return _state_response(
            launcher.start(timeout_seconds=body.timeout_seconds, wait=body.wait)
        )
    except (TimeoutError, RuntimeError) as exc:
        raise _mcp_conflict_error(exc) from exc
    except Exception as exc:
        raise _safe_service_error(exc, error="mcp_server_error") from exc


@router.post(
    "/mcp-server/stop",
    response_model=MCPServerStateResponse,
    responses=_error_response(),
)
def mcp_server_stop(
    body: MCPServerStopRequest | None = None,
    factory: LauncherFactory = Depends(get_mcp_launcher_factory),
) -> MCPServerStateResponse:
    body = body or MCPServerStopRequest()
    try:
        launcher = _mcp_launcher_from_config(factory, host=body.host, port=body.port)
        return _state_response(launcher.stop(timeout_seconds=body.timeout_seconds))
    except Exception as exc:
        raise _safe_service_error(exc, error="mcp_server_error") from exc


@router.post(
    "/mcp-server/restart",
    response_model=MCPServerStateResponse,
    responses={409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def mcp_server_restart(
    body: MCPServerRestartRequest | None = None,
    factory: LauncherFactory = Depends(get_mcp_launcher_factory),
) -> MCPServerStateResponse:
    body = body or MCPServerRestartRequest()
    try:
        launcher = _mcp_launcher_from_config(
            factory,
            host=body.host,
            port=body.port,
            context_url=body.context_url,
            write_mode=body.write_mode,
        )
        return _state_response(launcher.restart(timeout_seconds=body.timeout_seconds))
    except (TimeoutError, RuntimeError) as exc:
        raise _mcp_conflict_error(exc) from exc
    except Exception as exc:
        raise _safe_service_error(exc, error="mcp_server_error") from exc


app.include_router(router)
