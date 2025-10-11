import sys
import logging
from openai import OpenAI
from app.config import AppConfig
from app.logging_conf import setup_logging

logger = logging.getLogger("client")

def main() -> int:
    try:
        cfg = AppConfig.from_env()
    except Exception as e:
        print(f"[FATAL] Config error: {e}")
        return 2

    # Logging
    setup_logging(level=cfg.log_level, log_to_file=cfg.log_to_file, logs_dir=cfg.logs_dir)
    logger.info("Configuration Loaded. Model=%s, MCPs=%s, read_only=%s",
                cfg.model, [s.label for s in cfg.mcp_servers], cfg.read_only)

    # OpenAI Client
    try:
        client = OpenAI(api_key=cfg.openai_api_key)
    except Exception as e:
        logger.exception("Error inicializando OpenAI client")
        return 2

    # Tools (MCP servers)
    tools = cfg.build_tools()
    logger.debug("Tools publicadas a LLM: %s", tools)

    # Prompt
    user_prompt = "List all animals owned by \"Old MacDonald\""
    try:
        system_prompt_text = cfg.load_system_prompt()
        logger.info("Using system prompt file: %s", (cfg.prompts_dir / cfg.system_prompt_file))
    except Exception as e:
        logger.exception("No se pudo cargar el system prompt")
        print(f"[ERROR] No se pudo cargar el system prompt: {e}")
        return 2

    # Preservar el aviso de solo lectura como parte del prompt del sistema
    system_instructions = (
        f"{system_prompt_text}\n\n"
        f"Read only mode={cfg.read_only}. If something fails, explain why."
    )

    try:
        resp = client.responses.create(
            model=cfg.model,
            tools=tools, # type: ignore
            instructions=system_instructions,
            input=user_prompt,
            max_output_tokens=cfg.max_output_tokens,
        )
    except Exception as e:
        logger.exception("Failure in responses.create()")
        print(f"[ERROR] Failed model call: {e}")
        return 1

    # Éxito
    try:
        print(resp.output_text)
    except Exception:
        logger.warning("Couldn't retrieve output_text; printing response object.")
        print(resp)

    return 0

if __name__ == "__main__":
    sys.exit(main())

