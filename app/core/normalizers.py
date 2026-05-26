from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def extract_output_text(resp: Any) -> str:
    """Return a best-effort text representation from a provider response."""

    final_output = getattr(resp, "final_output", None)
    if final_output is not None:
        if isinstance(final_output, str):
            return final_output
        if isinstance(final_output, (dict, list)):
            return json.dumps(final_output, ensure_ascii=False)
        model_dump_json = getattr(final_output, "model_dump_json", None)
        if callable(model_dump_json):
            return model_dump_json()
        return str(final_output)

    try:
        output_text = resp.output_text  # type: ignore[attr-defined]
        if isinstance(output_text, str):
            return output_text
    except Exception:
        pass
    return str(resp)


def parse_output_json(output_text: str) -> Optional[Any]:
    if not output_text:
        return None
    try:
        return json.loads(output_text)
    except Exception:
        return None


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _parse_json_object(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {"_raw": raw}
        if isinstance(parsed, dict):
            return parsed
        return {"_raw": parsed}
    if raw is None:
        return {}
    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
        return {"_raw": dumped}
    return {"_raw": raw}


def _summarize_tool_output(raw_output: Any) -> Dict[str, Any]:
    output = _parse_json_object(raw_output)
    body = output.get("body")
    if body is None and output.get("type") == "text":
        text = output.get("text")
        if isinstance(text, str):
            try:
                body = json.loads(text)
            except Exception:
                body = text
    if body is None and "_raw" in output:
        body = output["_raw"]

    items_count = None
    body_preview = None
    if isinstance(body, list):
        items_count = len(body)
        body_preview = f"list[{items_count}]"
    elif isinstance(body, dict):
        body_preview = "object"
    elif body is not None:
        body_preview = str(body)[:120]

    return {
        "status": output.get("status"),
        "headers": output.get("headers"),
        "body_preview": body_preview,
        "items": items_count,
    }


def _extract_usage_dict(usage_data: Any) -> Dict[str, Any]:
    if not usage_data:
        return {}

    usage_dict: Dict[str, Any] = {
        "input_tokens": getattr(usage_data, "input_tokens", None),
        "output_tokens": getattr(usage_data, "output_tokens", None),
        "total_tokens": getattr(usage_data, "total_tokens", None),
    }
    output_details = getattr(usage_data, "output_tokens_details", None)
    if output_details:
        usage_dict["reasoning_tokens"] = getattr(output_details, "reasoning_tokens", None)
    return usage_dict


def _append_query_from_args(queries: List[str], args: Dict[str, Any]) -> None:
    params = args.get("params")
    if isinstance(params, str):
        queries.append(params)


def extract_mcp_trace_from_response(resp: Any) -> Dict[str, Any]:
    """
    Extract a stable MCP trace from a Responses-like provider object.

    Returns:
        {
          "calls": [...],
          "call_count": 3,
          "queries": ["/ngsi-ld/v1/entities?..."],
          "usage": {"input_tokens": 123, ...}
        }
    """

    calls: List[Dict[str, Any]] = []
    queries: List[str] = []

    output_items = getattr(resp, "output", []) or []
    for item in output_items:
        item_type = getattr(item, "type", None)
        if item_type != "mcp_call":
            continue

        name = getattr(item, "name", None)
        server_label = getattr(item, "server_label", None)

        raw_args = getattr(item, "arguments", None)
        args = _parse_json_object(raw_args)

        raw_output = getattr(item, "output", None)
        result = _summarize_tool_output(raw_output)

        calls.append(
            {
                "tool": name,
                "server_label": server_label,
                "arguments": args,
                "result": result,
            }
        )

        _append_query_from_args(queries, args)

    usage_data = getattr(resp, "usage", None)
    usage_dict = _extract_usage_dict(usage_data)

    return {
        "calls": calls,
        "call_count": len(calls),
        "queries": queries,
        "usage": usage_dict,
    }


def extract_mcp_trace_from_agents_result(result: Any) -> Dict[str, Any]:
    """Extract a stable MCP trace from an OpenAI Agents SDK RunResult."""

    calls: List[Dict[str, Any]] = []
    queries: List[str] = []
    pending_by_call_id: Dict[str, Dict[str, Any]] = {}
    seen_call_ids: set[str] = set()

    for item in getattr(result, "new_items", []) or []:
        item_type = getattr(item, "type", None)
        raw_item = getattr(item, "raw_item", None)
        raw_type = _get_value(raw_item, "type")

        if item_type == "tool_call_item":
            call_id = _get_value(raw_item, "call_id") or _get_value(raw_item, "id")
            args = _parse_json_object(_get_value(raw_item, "arguments"))
            call = {
                "tool": _get_value(raw_item, "name"),
                "server_label": _get_value(raw_item, "server_label"),
                "arguments": args,
                "result": _summarize_tool_output(_get_value(raw_item, "output")),
            }
            if raw_type == "mcp_call":
                calls.append(call)
                if call_id:
                    seen_call_ids.add(str(call_id))
                _append_query_from_args(queries, args)
            elif call_id:
                pending_by_call_id[str(call_id)] = call
            continue

        if item_type == "tool_call_output_item":
            call_id = _get_value(raw_item, "call_id")
            if not call_id:
                continue
            call = pending_by_call_id.pop(str(call_id), None)
            if not call:
                continue
            call["result"] = _summarize_tool_output(getattr(item, "output", None))
            calls.append(call)
            seen_call_ids.add(str(call_id))
            _append_query_from_args(queries, call.get("arguments") or {})

    # Hosted MCP calls may also be visible directly on raw model responses.
    for model_response in getattr(result, "raw_responses", []) or []:
        for output in getattr(model_response, "output", []) or []:
            if _get_value(output, "type") != "mcp_call":
                continue
            call_id = _get_value(output, "call_id") or _get_value(output, "id")
            if call_id and str(call_id) in seen_call_ids:
                continue
            args = _parse_json_object(_get_value(output, "arguments"))
            calls.append(
                {
                    "tool": _get_value(output, "name"),
                    "server_label": _get_value(output, "server_label"),
                    "arguments": args,
                    "result": _summarize_tool_output(_get_value(output, "output")),
                }
            )
            if call_id:
                seen_call_ids.add(str(call_id))
            _append_query_from_args(queries, args)

    usage_dict = _extract_usage_dict(getattr(getattr(result, "context_wrapper", None), "usage", None))
    if not usage_dict:
        usage_dict = _sum_raw_response_usage(getattr(result, "raw_responses", []) or [])

    return {
        "calls": calls,
        "call_count": len(calls),
        "queries": queries,
        "usage": usage_dict,
    }


def _sum_raw_response_usage(raw_responses: List[Any]) -> Dict[str, Any]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    reasoning_tokens = 0
    found = False
    for model_response in raw_responses:
        usage = _extract_usage_dict(getattr(model_response, "usage", None))
        if not usage:
            continue
        found = True
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
        value = usage.get("reasoning_tokens")
        if isinstance(value, int):
            reasoning_tokens += value
    if not found:
        return {}
    if reasoning_tokens:
        totals["reasoning_tokens"] = reasoning_tokens
    return totals
