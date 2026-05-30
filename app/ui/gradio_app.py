from __future__ import annotations

import argparse
import os
import time
from typing import Any, Iterator

import gradio as gr

from app.ui.api_client import ApiClientError, FiwareApiClient
from app.ui.state import (
    BROWSER_STATE_KEY,
    BROWSER_STATE_SECRET,
    active_messages,
    agent_choices,
    agent_supports_streaming,
    choose_agent_id,
    coerce_browser_state,
    create_new_session,
    empty_browser_state,
    ensure_active_session,
    save_session_messages,
    update_browser_preferences,
)


DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1"
DEFAULT_TRACE = {"call_count": 0, "queries": [], "usage": {}, "calls": []}
DATASETS = ["context-data-loader", "mcp-experiments"]

CSS = """
.fiware-status {
  font-size: 0.92rem;
}
.fiware-muted {
  color: #667085;
}
.fiware-sidebar button {
  min-width: 0;
}
"""


def build_app(api_base: str = DEFAULT_API_BASE) -> gr.Blocks:
    client = FiwareApiClient(api_base)

    with gr.Blocks(title="FIWARE Client") as demo:
        browser_state = _browser_state_component()
        ui_state = gr.State(_initial_ui_state(api_base))

        gr.Markdown(
            "# FIWARE Client\n"
            "Ask configured agents about FIWARE NGSI-LD data through MCP tools."
        )

        with gr.Row():
            with gr.Column(scale=1, min_width=300, elem_classes=["fiware-sidebar"]):
                api_status = gr.Markdown(elem_classes=["fiware-status"])
                agent = gr.Dropdown(label="Agent", choices=[], interactive=True)
                mode = gr.Radio(["Chat", "Question"], label="Mode", value="Chat")
                stream = gr.Checkbox(label="Stream responses", value=True)

                with gr.Accordion("Generation", open=False):
                    max_output_tokens = gr.Number(
                        label="Max output tokens",
                        value=30000,
                        precision=0,
                    )

                context_url = gr.Radio(
                    DATASETS,
                    label="Context dataset",
                    value="context-data-loader",
                )
                mcp_status = gr.JSON(label="MCP server", value={})
                with gr.Row():
                    start_btn = gr.Button("Start")
                    stop_btn = gr.Button("Stop")
                    restart_btn = gr.Button("Restart")
                refresh_btn = gr.Button("Refresh Status")

                with gr.Row():
                    new_chat_btn = gr.Button("New Chat")
                    clear_btn = gr.Button("Clear Visible Transcript")
                session_box = gr.Textbox(label="Session ID", interactive=False)

            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=520,
                )
                prompt = gr.Textbox(
                    label="Message",
                    placeholder="Ask about FIWARE entities, types, counts, or relationships...",
                    lines=3,
                )
                send_btn = gr.Button("Send", variant="primary")
                trace = gr.JSON(label="Last MCP trace", value=DEFAULT_TRACE)
                status = gr.Markdown(elem_classes=["fiware-status"])

        load_outputs = [
            api_status,
            agent,
            mode,
            stream,
            mcp_status,
            session_box,
            chatbot,
            trace,
            status,
            send_btn,
            start_btn,
            stop_btn,
            restart_btn,
            ui_state,
            browser_state,
        ]
        demo.load(
            _load_initial(client, api_base),
            inputs=[browser_state],
            outputs=load_outputs,
        )

        send_inputs = [
            prompt,
            agent,
            mode,
            stream,
            max_output_tokens,
            ui_state,
            browser_state,
        ]
        send_outputs = [
            chatbot,
            prompt,
            trace,
            status,
            session_box,
            ui_state,
            browser_state,
        ]
        send_btn.click(
            _send_message(client),
            inputs=send_inputs,
            outputs=send_outputs,
        )
        prompt.submit(
            _send_message(client),
            inputs=send_inputs,
            outputs=send_outputs,
        )

        refresh_btn.click(
            _refresh_mcp_status(client),
            inputs=[ui_state],
            outputs=[mcp_status, status, ui_state],
        )
        start_btn.click(
            _mcp_action(client, "start"),
            inputs=[context_url, ui_state],
            outputs=[mcp_status, status, ui_state],
        )
        stop_btn.click(
            _mcp_action(client, "stop"),
            inputs=[context_url, ui_state],
            outputs=[mcp_status, status, ui_state],
        )
        restart_btn.click(
            _mcp_action(client, "restart"),
            inputs=[context_url, ui_state],
            outputs=[mcp_status, status, ui_state],
        )

        agent.change(
            _change_agent,
            inputs=[agent, stream, ui_state, browser_state],
            outputs=[stream, status, ui_state, browser_state],
        )
        mode.change(
            _change_mode,
            inputs=[mode, ui_state, browser_state],
            outputs=[status, ui_state, browser_state],
        )
        stream.change(
            _change_stream,
            inputs=[stream, agent, ui_state, browser_state],
            outputs=[stream, status, ui_state, browser_state],
        )
        new_chat_btn.click(
            _new_chat,
            inputs=[agent, ui_state, browser_state],
            outputs=[chatbot, session_box, trace, status, ui_state, browser_state],
        )
        clear_btn.click(
            _clear_visible_transcript,
            inputs=[agent, ui_state, browser_state],
            outputs=[chatbot, trace, status, ui_state, browser_state],
        )

    return demo


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the FIWARE MCP Client Gradio UI.")
    parser.add_argument(
        "--api-base",
        default=os.getenv("FIWARE_API_BASE", DEFAULT_API_BASE),
        help="FastAPI base URL, including /api/v1.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Gradio host.")
    parser.add_argument("--port", type=int, default=7860, help="Gradio port.")
    args = parser.parse_args()

    demo = build_app(args.api_base).queue()
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        prevent_thread_lock=True,
        theme=gr.themes.Soft(primary_hue="teal", neutral_hue="zinc"),
        css=CSS,
        ssr_mode=False,
    )
    print(f"FIWARE Client UI running at http://{args.host}:{args.port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        close = getattr(demo, "close", None)
        if callable(close):
            close()


def _browser_state_component() -> Any:
    browser_state = getattr(gr, "BrowserState", None)
    if browser_state is None:
        return gr.State(empty_browser_state())
    for kwargs in (
        {
            "default_value": empty_browser_state(),
            "storage_key": BROWSER_STATE_KEY,
            "secret": BROWSER_STATE_SECRET,
        },
        {"value": empty_browser_state(), "key": BROWSER_STATE_KEY},
        {"value": empty_browser_state(), "storage_key": BROWSER_STATE_KEY},
        {"key": BROWSER_STATE_KEY},
        {"storage_key": BROWSER_STATE_KEY},
    ):
        try:
            return browser_state(**kwargs)
        except TypeError:
            continue
    return browser_state(empty_browser_state())


def _initial_ui_state(api_base: str) -> dict[str, Any]:
    return {
        "api_base": api_base,
        "runtime": None,
        "agents": [],
        "selected_agent_id": None,
        "session_id": None,
        "messages": [],
        "last_trace": DEFAULT_TRACE,
        "mcp_status": None,
        "api_connected": False,
    }


def _load_initial(client: FiwareApiClient, api_base: str):
    def load(browser_value: Any):
        ui_state = _initial_ui_state(api_base)
        browser = coerce_browser_state(browser_value)
        api_status = (
            f"**API:** Disconnected  \n"
            f"Backend unavailable at `{api_base}`. Start FastAPI with "
            "`uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000`."
        )
        status_text = ""
        runtime: dict[str, Any] | None = None
        agents_payload: dict[str, Any] = {"default_agent_id": None, "agents": []}
        mcp_payload: dict[str, Any] = {}
        connected = False

        try:
            health = client.health()
            runtime = client.runtime()
            agents_payload = client.agents()
            mcp_payload = client.mcp_status()
            connected = True
            api_status = (
                f"**API:** Connected  \n"
                f"`{health.get('service', 'fiware-mcp-client')}` "
                f"{health.get('version', '')}"
            )
        except ApiClientError as exc:
            status_text = _error_status(exc)

        agents = _agents_from_payload(agents_payload)
        selected_agent_id = choose_agent_id(
            agents,
            stored_agent_id=browser.get("selected_agent_id"),
            default_agent_id=agents_payload.get("default_agent_id")
            or (runtime or {}).get("default_agent_id"),
        )
        browser = update_browser_preferences(
            browser,
            selected_agent_id=selected_agent_id,
            mode=browser.get("mode", "Chat"),
            stream=browser.get("stream", True),
        )
        browser, session_id = ensure_active_session(
            browser,
            selected_agent_id=selected_agent_id,
        )
        messages = active_messages(browser)
        supports_stream = agent_supports_streaming(agents, selected_agent_id)
        stream_value = bool(browser.get("stream", True) and supports_stream)

        ui_state.update(
            {
                "runtime": runtime,
                "agents": agents,
                "selected_agent_id": selected_agent_id,
                "session_id": session_id,
                "messages": messages,
                "mcp_status": mcp_payload,
                "api_connected": connected,
            }
        )

        if connected:
            status_text = _mcp_summary(mcp_payload)

        return (
            api_status,
            gr.update(choices=agent_choices(agents), value=selected_agent_id),
            gr.update(value=browser.get("mode", "Chat")),
            gr.update(value=stream_value, interactive=supports_stream),
            mcp_payload,
            session_id,
            messages,
            DEFAULT_TRACE,
            status_text,
            gr.update(interactive=connected),
            gr.update(interactive=connected),
            gr.update(interactive=connected),
            gr.update(interactive=connected),
            ui_state,
            browser,
        )

    return load


def _send_message(client: FiwareApiClient):
    def send(
        prompt: str,
        selected_agent_id: str | None,
        mode: str,
        stream: bool,
        max_output_tokens: float | int | None,
        ui_state: dict[str, Any],
        browser_value: Any,
    ) -> Iterator[tuple[Any, ...]]:
        user_prompt = (prompt or "").strip()
        ui_state = _coerce_ui_state(ui_state)
        agents = ui_state.get("agents", [])
        selected_agent_id = selected_agent_id or ui_state.get("selected_agent_id")
        browser, session_id = ensure_active_session(
            browser_value,
            selected_agent_id=selected_agent_id,
        )
        messages = active_messages(browser)

        if not user_prompt:
            yield _send_outputs(
                messages,
                "",
                ui_state.get("last_trace") or DEFAULT_TRACE,
                "Enter a question first.",
                session_id,
                ui_state,
                browser,
            )
            return
        if not selected_agent_id:
            messages.append(
                {
                    "role": "assistant",
                    "content": "No agent is configured. Check the FastAPI backend configuration.",
                }
            )
            yield _send_outputs(
                messages,
                "",
                DEFAULT_TRACE,
                "No agent is available.",
                session_id,
                ui_state,
                browser,
            )
            return

        max_tokens = _normalize_max_tokens(max_output_tokens)
        messages.append({"role": "user", "content": user_prompt})
        browser = save_session_messages(
            browser,
            session_id=session_id,
            selected_agent_id=selected_agent_id,
            messages=messages,
        )
        ui_state.update(
            {
                "selected_agent_id": selected_agent_id,
                "session_id": session_id,
                "messages": messages,
            }
        )
        yield _send_outputs(
            messages,
            "",
            ui_state.get("last_trace") or DEFAULT_TRACE,
            "Sending...",
            session_id,
            ui_state,
            browser,
        )

        if mode == "Question":
            try:
                result = client.run(
                    prompt=user_prompt,
                    agent_id=selected_agent_id,
                    session_id=session_id,
                    max_output_tokens=max_tokens,
                )
            except ApiClientError as exc:
                yield _append_send_error(messages, browser, ui_state, session_id, selected_agent_id, exc)
                return
            yield _append_final_result(messages, browser, ui_state, session_id, selected_agent_id, result)
            return

        supports_stream = agent_supports_streaming(agents, selected_agent_id)
        if stream and supports_stream:
            yield from _send_streaming(
                client,
                messages,
                browser,
                ui_state,
                session_id,
                selected_agent_id,
                user_prompt,
                max_tokens,
            )
            return

        note = "Agent does not support streaming; using non-streaming chat." if stream else "Sending chat turn..."
        yield _send_outputs(
            messages,
            "",
            ui_state.get("last_trace") or DEFAULT_TRACE,
            note,
            session_id,
            ui_state,
            browser,
        )
        try:
            result = client.chat(
                prompt=user_prompt,
                agent_id=selected_agent_id,
                session_id=session_id,
                max_output_tokens=max_tokens,
            )
        except ApiClientError as exc:
            yield _append_send_error(messages, browser, ui_state, session_id, selected_agent_id, exc)
            return
        yield _append_final_result(messages, browser, ui_state, session_id, selected_agent_id, result)

    return send


def _send_streaming(
    client: FiwareApiClient,
    messages: list[dict[str, str]],
    browser: dict[str, Any],
    ui_state: dict[str, Any],
    session_id: str,
    selected_agent_id: str,
    user_prompt: str,
    max_tokens: int | None,
) -> Iterator[tuple[Any, ...]]:
    assistant_index = len(messages)
    messages.append({"role": "assistant", "content": ""})
    browser = save_session_messages(
        browser,
        session_id=session_id,
        selected_agent_id=selected_agent_id,
        messages=messages,
    )
    yield _send_outputs(
        messages,
        "",
        ui_state.get("last_trace") or DEFAULT_TRACE,
        "Streaming...",
        session_id,
        ui_state,
        browser,
    )

    try:
        events = client.chat_stream(
            prompt=user_prompt,
            agent_id=selected_agent_id,
            session_id=session_id,
            max_output_tokens=max_tokens,
        )
        final_seen = False
        for event in events:
            event_type = event.get("type")
            if event_type == "delta":
                messages[assistant_index]["content"] += str(event.get("content") or "")
                browser = save_session_messages(
                    browser,
                    session_id=session_id,
                    selected_agent_id=selected_agent_id,
                    messages=messages,
                )
                ui_state["messages"] = messages
                yield _send_outputs(
                    messages,
                    "",
                    ui_state.get("last_trace") or DEFAULT_TRACE,
                    "Streaming...",
                    session_id,
                    ui_state,
                    browser,
                )
                continue
            if event_type == "final":
                final_seen = True
                result = event.get("result") if isinstance(event.get("result"), dict) else {}
                text = _result_text(result)
                if text:
                    messages[assistant_index]["content"] = text
                trace = _trace_from_result(result)
                ui_state["last_trace"] = trace
                browser = save_session_messages(
                    browser,
                    session_id=session_id,
                    selected_agent_id=selected_agent_id,
                    messages=messages,
                )
                ui_state["messages"] = messages
                yield _send_outputs(
                    messages,
                    "",
                    trace,
                    _result_status(result),
                    session_id,
                    ui_state,
                    browser,
                )
                continue
            if event_type == "error":
                messages[assistant_index]["content"] = _stream_error_text(event)
                browser = save_session_messages(
                    browser,
                    session_id=session_id,
                    selected_agent_id=selected_agent_id,
                    messages=messages,
                )
                ui_state["messages"] = messages
                yield _send_outputs(
                    messages,
                    "",
                    ui_state.get("last_trace") or DEFAULT_TRACE,
                    "Streaming failed.",
                    session_id,
                    ui_state,
                    browser,
                )
                return
        if not final_seen:
            ui_state["messages"] = messages
            yield _send_outputs(
                messages,
                "",
                ui_state.get("last_trace") or DEFAULT_TRACE,
                "Stream ended before a final result arrived.",
                session_id,
                ui_state,
                browser,
            )
    except ApiClientError as exc:
        messages[assistant_index]["content"] = f"Backend error: {exc.message}"
        browser = save_session_messages(
            browser,
            session_id=session_id,
            selected_agent_id=selected_agent_id,
            messages=messages,
        )
        ui_state["messages"] = messages
        yield _send_outputs(
            messages,
            "",
            ui_state.get("last_trace") or DEFAULT_TRACE,
            _error_status(exc),
            session_id,
            ui_state,
            browser,
        )


def _append_final_result(
    messages: list[dict[str, str]],
    browser: dict[str, Any],
    ui_state: dict[str, Any],
    session_id: str,
    selected_agent_id: str,
    result: dict[str, Any],
) -> tuple[Any, ...]:
    messages.append({"role": "assistant", "content": _result_text(result)})
    trace = _trace_from_result(result)
    browser = save_session_messages(
        browser,
        session_id=session_id,
        selected_agent_id=selected_agent_id,
        messages=messages,
    )
    ui_state["messages"] = messages
    ui_state["last_trace"] = trace
    return _send_outputs(
        messages,
        "",
        trace,
        _result_status(result),
        session_id,
        ui_state,
        browser,
    )


def _append_send_error(
    messages: list[dict[str, str]],
    browser: dict[str, Any],
    ui_state: dict[str, Any],
    session_id: str,
    selected_agent_id: str,
    exc: ApiClientError,
) -> tuple[Any, ...]:
    messages.append({"role": "assistant", "content": f"Backend error: {exc.message}"})
    browser = save_session_messages(
        browser,
        session_id=session_id,
        selected_agent_id=selected_agent_id,
        messages=messages,
    )
    ui_state["messages"] = messages
    return _send_outputs(
        messages,
        "",
        ui_state.get("last_trace") or DEFAULT_TRACE,
        _error_status(exc),
        session_id,
        ui_state,
        browser,
    )


def _refresh_mcp_status(client: FiwareApiClient):
    def refresh(ui_state: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
        ui_state = _coerce_ui_state(ui_state)
        try:
            payload = client.mcp_status()
        except ApiClientError as exc:
            return {}, _error_status(exc), ui_state
        ui_state["mcp_status"] = payload
        return payload, _mcp_summary(payload), ui_state

    return refresh


def _mcp_action(client: FiwareApiClient, action: str):
    def run_action(context_url: str, ui_state: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
        ui_state = _coerce_ui_state(ui_state)
        try:
            if action == "start":
                payload = client.mcp_start(context_url=context_url)
                message = "MCP server start requested."
            elif action == "stop":
                payload = client.mcp_stop()
                message = "MCP server stop requested."
            else:
                payload = client.mcp_restart(context_url=context_url)
                message = "MCP server restart requested."
        except ApiClientError as exc:
            return ui_state.get("mcp_status") or {}, _error_status(exc), ui_state
        ui_state["mcp_status"] = payload
        return payload, f"{message}  \n{_mcp_summary(payload)}", ui_state

    return run_action


def _change_agent(
    selected_agent_id: str | None,
    current_stream: bool,
    ui_state: dict[str, Any],
    browser_value: Any,
) -> tuple[Any, str, dict[str, Any], dict[str, Any]]:
    ui_state = _coerce_ui_state(ui_state)
    agents = ui_state.get("agents", [])
    supports_stream = agent_supports_streaming(agents, selected_agent_id)
    stream_value = bool(current_stream and supports_stream)
    ui_state["selected_agent_id"] = selected_agent_id
    browser = update_browser_preferences(
        browser_value,
        selected_agent_id=selected_agent_id,
        stream=stream_value,
    )
    note = "Future turns will use the selected agent."
    if not supports_stream:
        note += " Streaming is unavailable for this agent."
    return gr.update(value=stream_value, interactive=supports_stream), note, ui_state, browser


def _change_mode(
    mode: str,
    ui_state: dict[str, Any],
    browser_value: Any,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    ui_state = _coerce_ui_state(ui_state)
    browser = update_browser_preferences(browser_value, mode=mode)
    return f"Mode set to {mode}.", ui_state, browser


def _change_stream(
    stream: bool,
    selected_agent_id: str | None,
    ui_state: dict[str, Any],
    browser_value: Any,
) -> tuple[Any, str, dict[str, Any], dict[str, Any]]:
    ui_state = _coerce_ui_state(ui_state)
    supports_stream = agent_supports_streaming(ui_state.get("agents", []), selected_agent_id)
    stream_value = bool(stream and supports_stream)
    browser = update_browser_preferences(browser_value, stream=stream_value)
    if stream and not supports_stream:
        return gr.update(value=False, interactive=False), "Selected agent does not support streaming.", ui_state, browser
    return gr.update(value=stream_value, interactive=supports_stream), "Streaming preference updated.", ui_state, browser


def _new_chat(
    selected_agent_id: str | None,
    ui_state: dict[str, Any],
    browser_value: Any,
) -> tuple[list[dict[str, str]], str, dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    ui_state = _coerce_ui_state(ui_state)
    browser, session_id = create_new_session(
        browser_value,
        selected_agent_id=selected_agent_id or ui_state.get("selected_agent_id"),
    )
    ui_state.update({"session_id": session_id, "messages": [], "last_trace": DEFAULT_TRACE})
    return [], session_id, DEFAULT_TRACE, "New chat created.", ui_state, browser


def _clear_visible_transcript(
    selected_agent_id: str | None,
    ui_state: dict[str, Any],
    browser_value: Any,
) -> tuple[list[dict[str, str]], dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    ui_state = _coerce_ui_state(ui_state)
    browser, session_id = ensure_active_session(
        browser_value,
        selected_agent_id=selected_agent_id or ui_state.get("selected_agent_id"),
    )
    browser = save_session_messages(
        browser,
        session_id=session_id,
        selected_agent_id=selected_agent_id or ui_state.get("selected_agent_id"),
        messages=[],
    )
    ui_state.update({"messages": [], "last_trace": DEFAULT_TRACE})
    return [], DEFAULT_TRACE, "Visible transcript cleared. Backend chat memory is unchanged.", ui_state, browser


def _send_outputs(
    messages: list[dict[str, str]],
    prompt_value: str,
    trace: dict[str, Any],
    status: str,
    session_id: str,
    ui_state: dict[str, Any],
    browser: dict[str, Any],
) -> tuple[Any, ...]:
    return messages, prompt_value, trace, status, session_id, ui_state, browser


def _coerce_ui_state(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        state = dict(value)
    else:
        state = _initial_ui_state(DEFAULT_API_BASE)
    state.setdefault("agents", [])
    state.setdefault("last_trace", DEFAULT_TRACE)
    return state


def _agents_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    agents = payload.get("agents")
    return agents if isinstance(agents, list) else []


def _normalize_max_tokens(value: float | int | None) -> int | None:
    if value is None:
        return None
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return None
    return tokens if tokens > 0 else None


def _result_text(result: dict[str, Any]) -> str:
    if not result.get("ok", False):
        return f"The model/tool run failed: {result.get('error') or 'Unknown error'}"
    return str(result.get("output_text") or "(No text returned.)")


def _result_status(result: dict[str, Any]) -> str:
    trace = _trace_from_result(result)
    model = result.get("model_name") or "model"
    return f"Done with `{model}`. MCP calls: {trace.get('call_count', 0)}."


def _trace_from_result(result: dict[str, Any]) -> dict[str, Any]:
    trace = result.get("mcp_trace")
    return trace if isinstance(trace, dict) else DEFAULT_TRACE


def _error_status(exc: ApiClientError) -> str:
    status = f"HTTP {exc.status_code}: " if exc.status_code else ""
    return f"{status}{exc.message}"


def _stream_error_text(event: dict[str, Any]) -> str:
    return f"Streaming failed: {event.get('message') or event.get('error') or 'Unknown error'}"


def _mcp_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "MCP server status is unavailable."
    running = "running" if payload.get("running") else "stopped"
    reachable = "reachable" if payload.get("reachable") else "not reachable"
    endpoint = payload.get("endpoint") or "unknown endpoint"
    return f"MCP server: {running}, {reachable} at `{endpoint}`."


if __name__ == "__main__":
    main()
