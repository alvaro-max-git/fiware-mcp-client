import csv
import json
import logging
from pathlib import Path
from typing import Dict, Any, Iterable

from app.config import AppConfig
from app.types import RunRequest, ExpectedSpec, LLMJudgeSpec
from app.runner import run_once, _summarize_tools
from app.evaluator import evaluate

logger = logging.getLogger("benchmark")

def load_rows(csv_file: Path) -> Iterable[Dict[str, str]]:
    with csv_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            yield row

def parse_expected(row: Dict[str, str]) -> ExpectedSpec:
    raw = row.get("expected") or ""
    if not raw.strip():
        return ExpectedSpec()
    data = json.loads(raw)
    if "gold" in data:
        return ExpectedSpec(llm_judge=LLMJudgeSpec.from_dict(data))
    # ...otros modos según tus necesidades...
    return ExpectedSpec()

def run_benchmark(cfg: AppConfig, csv_file: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "results.csv"

    with out_csv.open("w", encoding="utf-8", newline="") as f_out:
        fieldnames = [
            "id", "passed", "reason", "model", "system_prompt_file", "eval_mode",
            "question", "output_text",
            "score_correctness", "score_reasoning", "score_efficiency", "score_total",
            "mcp_call_count", "queries",
        ]
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()

        for row in load_rows(csv_file):
            row_id = row.get("id") or ""
            question = row.get("question") or ""
            system_prompt_file = row.get("system_prompt_file") or None
            eval_mode = row.get("eval_mode") or ""
            row_model = row.get("model") or None

            original_model = cfg.model
            if row_model:
                cfg.model = row_model

            req = RunRequest(user_prompt=question, system_prompt_file=system_prompt_file)

            # Log de tools efectivos para esta fila
            tools = cfg.build_tools()
            logger.info(
                "Benchmark row id=%s tools summary: %s",
                row_id,
                _summarize_tools(tools),
            )

            res = run_once(cfg, req)

            cfg.model = original_model

            expected = parse_expected(row)
            eval_res = evaluate(cfg, res, expected)

            mcp_trace = res.metadata.get("mcp_trace") or {}
            mcp_calls = mcp_trace.get("call_count", 0)
            queries = mcp_trace.get("queries") or []

            row_out = {
                "id": row_id,
                "passed": eval_res.passed,
                "reason": eval_res.reason or "",
                "model": res.model,
                "system_prompt_file": system_prompt_file or "",
                "eval_mode": eval_mode,
                "question": question,
                "output_text": res.output_text,
                "score_correctness": (eval_res.details.get("scores", {}) or {}).get("correctness"),
                "score_reasoning": (eval_res.details.get("scores", {}) or {}).get("reasoning"),
                "score_efficiency": (eval_res.details.get("scores", {}) or {}).get("efficiency"),
                "score_total": (eval_res.details.get("scores", {}) or {}).get("weighted_total"),
                "mcp_call_count": mcp_calls,
                "queries": json.dumps(queries, ensure_ascii=False),
            }
            writer.writerow(row_out)

    return out_csv