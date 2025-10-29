import sys
import argparse
import logging
import json
from pathlib import Path
from app.config import AppConfig
from app.logging_conf import setup_logging
from app.runner import run_once
from app.types import RunRequest, ExpectedSpec
from app.evaluator import evaluate
from benchmark.csv_runner import run_benchmark

logger = logging.getLogger("client")

def _debug_dump_mcp_trace(metadata: dict, label: str = "") -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    if not isinstance(metadata, dict):
        return
    # Expect the structured dict created by app.runner._extract_mcp_trace_from_response
    trace = metadata.get("mcp_trace") or metadata.get("mcp_traces")
    if not trace:
        return
    try:
        trace_str = json.dumps(trace, ensure_ascii=False, indent=2)
    except Exception:
        trace_str = str(trace)
    header = f"MCP trace [{label}]" if label else "MCP trace"
    logger.debug("%s:\n%s", header, trace_str)

def cmd_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    req = RunRequest(user_prompt=args.prompt, system_prompt_file=args.system_prompt_file)
    res = run_once(cfg, req)
    print(res.output_text if res.ok else f"[ERROR] {res.error}")
    _debug_dump_mcp_trace(getattr(res, "metadata", {}), label="run")

    return 0 if res.ok else 1

def cmd_eval(cfg: AppConfig, args: argparse.Namespace) -> int:
    req = RunRequest(user_prompt=args.prompt, system_prompt_file=args.system_prompt_file)
    res = run_once(cfg, req)

    expected = ExpectedSpec()
    if args.exact_text:
        expected.exact_text = args.exact_text
    if args.equals_json:
        import json
        expected.equals_json = json.loads(args.equals_json)
    if args.json_subset:
        import json
        expected.json_subset = json.loads(args.json_subset)
    if args.regex:
        expected.regex = args.regex

    ev = evaluate(res, expected)
    print(res.output_text)
    print(f"\n[EVAL] passed={ev.passed} reason={ev.reason or ''}")
    _debug_dump_mcp_trace(getattr(res, "metadata", {}), label="eval")
    return 0 if ev.passed else 2

def cmd_bench(cfg: AppConfig, args: argparse.Namespace) -> int:
    out = run_benchmark(cfg, Path(args.csv), Path(args.out))
    print(f"Benchmark results: {out}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fiware-mcp-client")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run")
    pr.add_argument("--prompt", required=True)
    pr.add_argument("--system-prompt-file", default=None)
    pr.set_defaults(func=cmd_run)

    pe = sub.add_parser("eval")
    pe.add_argument("--prompt", required=True)
    pe.add_argument("--system-prompt-file", default=None)
    pe.add_argument("--exact-text")
    pe.add_argument("--equals-json")
    pe.add_argument("--json-subset")
    pe.add_argument("--regex")
    pe.set_defaults(func=cmd_eval)

    pb = sub.add_parser("bench")
    pb.add_argument("--csv", required=True)
    pb.add_argument("--out", default="bench_out")
    pb.set_defaults(func=cmd_bench)

    return p

def main() -> int:
    try:
        cfg = AppConfig.from_env()
    except Exception as e:
        print(f"[FATAL] Config error: {e}")
        return 2

    setup_logging(level=cfg.log_level, log_to_file=cfg.log_to_file, logs_dir=cfg.logs_dir)

    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(cfg, args)
    except Exception as e:
        logger.exception("Command failed")
        print(f"[ERROR] {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

