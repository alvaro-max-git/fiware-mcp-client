from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional
from openai import OpenAI
from app.config import AppConfig
from app.prompts import load_prompt
from app.types import RunRequest, RunResult

logger = logging.getLogger("runner")

def build_system_instructions(cfg: AppConfig, system_prompt_file: Optional[str]) -> str:
    fname = system_prompt_file or cfg.system_prompt_file
    system_prompt_text = load_prompt(cfg.prompts_dir, fname)
    return f"{system_prompt_text}\n\nRead only mode={cfg.read_only}. If something fails, explain why."

def build_client(cfg: AppConfig) -> OpenAI:
    return OpenAI(api_key=cfg.openai_api_key)


def _extract_mcp_trace_from_response(resp: Any) -> Dict[str, Any]:
    """
    Returns: {
      "calls": [
        {
          "tool": "execute_query",
          "server_label": "fiware-mcp",
          "arguments": {"params": "..."},
          "result": {"status": 200, "headers": {...}, "body_preview": "...", "items": 13}
        },
        ...
      ],
      "call_count": 3,
      "queries": ["/ngsi-ld/v1/entities?...","/ngsi-ld/v1/entities?...", ...],
      "usage": {
        "input_tokens": 123,
        "output_tokens": 456,
        "total_tokens": 579,
        "reasoning_tokens": 300
      }
    }
    """
    calls: List[Dict] = []
    queries: List[str] = []

    # 1) Recorrer resp.output si existe
    output_items = getattr(resp, "output", []) or []
    for it in output_items:
        it_type = getattr(it, "type", None)
        if it_type == "mcp_call":
            name = getattr(it, "name", None)
            server_label = getattr(it, "server_label", None)

            # arguments llega como string JSON → parse seguro
            raw_args = getattr(it, "arguments", None)
            args = {}
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {"_raw": raw_args}

            # output llega como string JSON → parse seguro
            raw_out = getattr(it, "output", None)
            out = {}
            items_count = None
            body_preview = None
            if isinstance(raw_out, str):
                try:
                    out = json.loads(raw_out)
                    body = out.get("body")
                    # Para métricas rápidas
                    if isinstance(body, list):
                        items_count = len(body)
                        # preview corto para logs (evitar tochar enormes)
                        body_preview = f"list[{items_count}]"
                    elif isinstance(body, dict):
                        body_preview = "object"
                    elif body is None:
                        body_preview = None
                    else:
                        body_preview = str(body)[:120]
                except Exception:
                    out = {"_raw": raw_out}

            entry = {
                "tool": name,
                "server_label": server_label,
                "arguments": args,
                "result": {
                    "status": out.get("status"),
                    "headers": out.get("headers"),
                    "body_preview": body_preview,
                    "items": items_count,
                },
            }
            calls.append(entry)

            # Si es execute_query y hay params → es la query
            params = args.get("params")
            if isinstance(params, str):
                queries.append(params)

        elif it_type == "mcp_list_tools":
            # opcional: registrar tools disponibles si te sirve
            pass

    usage_data = getattr(resp, "usage", None)
    usage_dict = {}
    if usage_data:
        usage_dict = {
            "input_tokens": getattr(usage_data, "input_tokens", None),
            "output_tokens": getattr(usage_data, "output_tokens", None),
            "total_tokens": getattr(usage_data, "total_tokens", None),
        }
        output_details = getattr(usage_data, "output_tokens_details", None)
        if output_details:
            usage_dict["reasoning_tokens"] = getattr(output_details, "reasoning_tokens", None)


    return {
        "calls": calls,
        "call_count": len(calls),
        "queries": queries,
        "usage": usage_dict,
    }   


def _summarize_tools(tools: list[dict]) -> list[dict]:
	"""Return a redacted view of the OpenAI tools payload for logging/debug."""
	summary: list[dict] = []
	for tool in tools:
		entry = {"type": tool.get("type")}
		if tool.get("type") == "mcp":
			entry["label"] = tool.get("server_label")
			entry["allowed_tools"] = tool.get("allowed_tools")
		elif tool.get("type") == "code_interpreter":
			entry["memory_limit"] = (tool.get("container") or {}).get("memory_limit")
		summary.append(entry)
	return summary

def _extract_code_interpreter_calls(resp) -> list[dict]:
	try:
		payload = resp.model_dump()
	except Exception:
		try:
			payload = resp.to_dict()
		except Exception:
			return []
	calls: list[dict] = []
	for item in payload.get("output", []) or []:
		if item.get("type") != "tool_call":
			continue
		name = item.get("name") or item.get("tool", {}).get("name")
		if name != "code_interpreter":
			continue
		calls.append({
			"id": item.get("id"),
			"status": item.get("status"),
			"name": name,
			"args_keys": list((item.get("arguments") or {}).keys()),
		})
	return calls

def run_once(cfg: AppConfig, request: RunRequest) -> RunResult:
    try:
        client = build_client(cfg)
        tools = cfg.build_tools()

        code_interp_enabled = any(t.get("type") == "code_interpreter" for t in tools)

        # Log the tools we are about to send (always)
        logger.info(
            "OpenAI tools payload (code_interpreter=%s): %s",
            code_interp_enabled,
            _summarize_tools(tools),
        )

        if not code_interp_enabled:
            logger.warning(
                "Request sent WITHOUT Code Interpreter tool. "
                "Ensure ENABLE_CODE_INTERPRETER is not set to 'false' in the environment."
            )

        instructions = build_system_instructions(cfg, request.system_prompt_file)

        resp = client.responses.create(
            model=cfg.model,
            tools=tools,  # type: ignore
            instructions=instructions,
            input=request.user_prompt,
            max_output_tokens=request.max_output_tokens or cfg.max_output_tokens,
        )

        output_text = ""
        try:
            output_text = resp.output_text  # type: ignore[attr-defined]
        except Exception:
            output_text = str(resp)

        parsed = None
        if output_text:
            try:
                parsed = json.loads(output_text)
            except Exception:
                parsed = None

        mcp_trace = _extract_mcp_trace_from_response(resp)
        code_interp_calls = _extract_code_interpreter_calls(resp)
        if code_interp_calls:
            logger.info("Code Interpreter executed %d time(s)", len(code_interp_calls))
        else:
            logger.debug("Code Interpreter was not invoked during this run")

        metadata = {
            "tools": tools,
            "mcp_trace": mcp_trace,
            "code_interpreter": {
                "enabled": code_interp_enabled,
                "calls": code_interp_calls,
            },
        }

        return RunResult(
            ok=True,
            output_text=output_text,
            raw_response=resp,
            model=cfg.model,
            parsed_json=parsed,
            metadata=metadata,
        )
    except Exception as e:
        logger.exception("run_once failed")
        return RunResult(ok=False, output_text="", error=str(e), model=cfg.model)

# --- NEW: modo debug simple -------------------------------------------------

if __name__ == "__main__":
    # Permite comprobar desde CLI qué tools se están construyendo realmente.
    cfg = AppConfig.from_env()
    tools = cfg.build_tools()
    logger.setLevel(logging.INFO)
    logger.info("Debug run: tools built = %s", _summarize_tools(tools))
    print(json.dumps(_summarize_tools(tools), indent=2))