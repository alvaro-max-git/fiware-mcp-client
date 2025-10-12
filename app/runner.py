from __future__ import annotations
import json
import logging
from typing import Optional
from openai import OpenAI
from app.config import AppConfig
from app.prompts import load_prompt
from app.types import RunRequest, RunResult

log = logging.getLogger("runner")

def build_system_instructions(cfg: AppConfig, system_prompt_file: Optional[str]) -> str:
    fname = system_prompt_file or cfg.system_prompt_file
    system_prompt_text = load_prompt(cfg.prompts_dir, fname)
    return f"{system_prompt_text}\n\nRead only mode={cfg.read_only}. If something fails, explain why."

def build_client(cfg: AppConfig) -> OpenAI:
    return OpenAI(api_key=cfg.openai_api_key)

def run_once(cfg: AppConfig, req: RunRequest) -> RunResult:
    try:
        client = build_client(cfg)
        tools = cfg.build_tools()
        instructions = build_system_instructions(cfg, req.system_prompt_file)

        resp = client.responses.create(
            model=cfg.model,
            tools=tools,  # type: ignore
            instructions=instructions,
            input=req.user_prompt,
            max_output_tokens=req.max_output_tokens or cfg.max_output_tokens,
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

        return RunResult(
            ok=True,
            output_text=output_text,
            raw_response=resp,
            model=cfg.model,
            parsed_json=parsed,
            metadata={"tools": tools},
        )
    except Exception as e:
        log.exception("run_once failed")
        return RunResult(ok=False, output_text="", error=str(e), model=cfg.model)