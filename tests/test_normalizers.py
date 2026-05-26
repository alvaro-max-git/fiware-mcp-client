from types import SimpleNamespace

from app.core.normalizers import (
    extract_mcp_trace_from_agents_result,
    extract_mcp_trace_from_response,
    extract_output_text,
    parse_output_json,
)


def test_extract_mcp_trace_from_response_collects_calls_queries_and_usage():
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="mcp_call",
                name="execute_query",
                server_label="fiware-mcp",
                arguments='{"params": "GET /ngsi-ld/v1/entities"}',
                output='{"status": 200, "headers": {"content-type": "application/json"}, "body": [{"id": "1"}]}',
            )
        ],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
    )

    trace = extract_mcp_trace_from_response(response)

    assert trace["call_count"] == 1
    assert trace["queries"] == ["GET /ngsi-ld/v1/entities"]
    assert trace["calls"][0]["result"]["items"] == 1
    assert trace["usage"]["reasoning_tokens"] == 5


def test_parse_output_json_returns_none_for_non_json_text():
    assert parse_output_json("plain text") is None


def test_extract_output_text_prefers_agents_final_output():
    result = SimpleNamespace(final_output={"ok": True}, output_text="provider text")

    assert extract_output_text(result) == '{"ok": true}'


def test_extract_mcp_trace_from_agents_result_collects_local_mcp_function_calls():
    result = SimpleNamespace(
        new_items=[
            SimpleNamespace(
                type="tool_call_item",
                raw_item=SimpleNamespace(
                    type="function_call",
                    call_id="call-1",
                    name="execute_query",
                    arguments='{"params": "GET /ngsi-ld/v1/entities"}',
                ),
            ),
            SimpleNamespace(
                type="tool_call_output_item",
                raw_item={"type": "function_call_output", "call_id": "call-1"},
                output='{"type": "text", "text": "[{\\"id\\": \\"urn:ngsi-ld:Entity:1\\"}]"}',
            ),
        ],
        raw_responses=[],
        context_wrapper=SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=12,
                output_tokens=8,
                total_tokens=20,
                output_tokens_details=SimpleNamespace(reasoning_tokens=3),
            )
        ),
    )

    trace = extract_mcp_trace_from_agents_result(result)

    assert trace["call_count"] == 1
    assert trace["queries"] == ["GET /ngsi-ld/v1/entities"]
    assert trace["calls"][0]["tool"] == "execute_query"
    assert trace["calls"][0]["result"]["items"] == 1
    assert trace["usage"]["reasoning_tokens"] == 3
