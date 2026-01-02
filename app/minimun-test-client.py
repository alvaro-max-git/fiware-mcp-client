"""Historical minimal client (kept intentionally).

This script shows the smallest possible OpenAI Responses + MCP call.

Preferred config source: `config.yaml` -> `mcp_servers`.
Secrets: `.env` (e.g. OPENAI_API_KEY).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from openai import OpenAI

from app.core.config import AppConfig, apply_client_config_overrides, load_client_config


DEFAULT_PROMPT = "Use the tools to retrieve all entities with limit=5 and summarize how many entities you retrieved and their types."


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml (default: config.yaml)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="User prompt")
    parser.add_argument("--model", default=None, help="Override model (otherwise uses config/env default)")
    parser.add_argument("--max-output-tokens", type=int, default=800, help="Max output tokens")
    args = parser.parse_args()

    cfg = AppConfig.from_env(require_mcp=False)

    try:
        client_cfg = load_client_config(Path(args.config))
        cfg = apply_client_config_overrides(cfg, client_cfg)
    except FileNotFoundError:
        # Historical fallback: allow MCP_URL in env for one-off quick tests.
        pass

    tools = cfg.build_tools()
    if not tools:
        mcp_url = os.getenv("MCP_URL")
        if not mcp_url:
            raise SystemExit(
                "No MCP tools configured. Add mcp_servers to config.yaml (preferred) or set MCP_URL in .env."
            )
        tools = [
            {
                "type": "mcp",
                "server_label": os.getenv("MCP_LABEL") or "fiware-mcp",
                "server_url": mcp_url,
                "allowed_tools": ["CB_version", "get_all_entities", "get_entity_types"],
                "require_approval": "never",
            }
        ]

    client = OpenAI(api_key=cfg.openai_api_key)
    response = client.responses.create(
        model=args.model or cfg.model,
        tools=tools,  # type: ignore
        instructions=(
            "You are a client that answers questions from the user and queries a Context Broker via MCP to retrieve answers."
        ),
        input=args.prompt,
        max_output_tokens=args.max_output_tokens,
    )
    print(response.output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())