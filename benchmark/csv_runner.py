import csv
import json
import logging
from pathlib import Path
from typing import Dict, Any, Iterable
from app.config import AppConfig
from app.runner import run_once
from app.types import RunRequest, ExpectedSpec, LLMJudgeSpec, LLMJudgeGold
from app.evaluator import evaluate, evaluate_llm_judge

# CSV columns:
# id, question, model, system_prompt_file, eval_mode, expected
# where expected can be JSON (for equals_json/json_subset/llm_judge) or plain text/regex.

def _detect_delimiter(sample: str) -> str:
    header = sample.splitlines()[0] if sample else ""
    candidates = [",", ";", "|", "\t"]
    counts = {d: header.count(d) for d in candidates}
    best = max(candidates, key=counts.get) # type: ignore
    if counts.get(best):
        return best
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(candidates)).delimiter
    except csv.Error:
        return ","

def load_rows(csv_path: Path) -> Iterable[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        delimiter = _detect_delimiter(sample)
        reader = csv.DictReader(f, delimiter=delimiter, skipinitialspace=True)
        for raw_row in reader:
            if not raw_row:
                continue
            yield {
                (k.strip() if isinstance(k, str) else k): (v.strip() if isinstance(v, str) else v)
                for k, v in raw_row.items()
            }

def parse_expected(row: Dict[str, str]) -> tuple[ExpectedSpec, LLMJudgeSpec | None]:
    """Returns (ExpectedSpec, optional LLMJudgeSpec)"""
    mode = (row.get("eval_mode") or "").strip()
    raw = row.get("expected") or ""
    
    if mode == "llm_judge":
        try:
            data = json.loads(raw) if raw else {}
        except Exception as e:
            logging.getLogger("benchmark").error(f"Failed to parse llm_judge JSON for row {row.get('id')}: {e}")
            return ExpectedSpec(), None
        
        gold_data = data.get("gold", {})
        gold = LLMJudgeGold(
            answer_text=gold_data.get("answer_text"),
            answer_json=gold_data.get("answer_json"),
            numeric=gold_data.get("numeric"),
            reasoning=gold_data.get("reasoning"),
            queries=gold_data.get("queries") or [],
        )
        spec = LLMJudgeSpec(
            gold=gold,
            weights=data.get("weights") or {"correctness": 0.7, "reasoning": 0.2, "efficiency": 0.1},
            pass_threshold=float(data.get("pass_threshold", 0.8)),
            grading_mode=data.get("grading_mode", "gated"),
            min_correctness=float(data.get("min_correctness", 1.0)),
            efficiency_budget=data.get("efficiency_budget"),
            notes=data.get("notes"),
        )
        return ExpectedSpec(llm_judge=spec), spec
    
    if mode in ("equals_json", "json_subset"):
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if mode == "equals_json":
            return ExpectedSpec(equals_json=data), None
        return ExpectedSpec(json_subset=data), None
    
    if mode == "exact_text":
        return ExpectedSpec(exact_text=raw), None
    
    if mode == "regex":
        return ExpectedSpec(regex=raw), None
    
    return ExpectedSpec(), None

def run_benchmark(cfg: AppConfig, csv_file: Path, out_path: Path) -> Path:
    out_is_file = out_path.suffix.lower() == ".csv" or (out_path.exists() and out_path.is_file())
    if out_is_file:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        results_csv = out_path
    else:
        out_path.mkdir(parents=True, exist_ok=True)
        results_csv = out_path / "results.csv"
    bench_logger = logging.getLogger("benchmark")

    with results_csv.open("w", encoding="utf-8", newline="") as f_out:
        writer = csv.DictWriter(
            f_out,
            fieldnames=[
                "id","passed","reason","model","system_prompt_file","eval_mode",
                "question","output_text",
                "score_correctness","score_reasoning","score_efficiency","score_total",
                "mcp_call_count","queries"
            ],
        )
        writer.writeheader()

        for row in load_rows(csv_file):
            row_id = row.get("id") or ""
            row_model = (row.get("model") or "").strip()
            original_model = cfg.model
            if row_model:
                cfg.model = row_model

            question = (row.get("question") or "").strip()
            system_prompt_file = (row.get("system_prompt_file") or "").strip() or None
            eval_mode = (row.get("eval_mode") or "").strip()

            if not question:
                bench_logger.error("Row %s is missing a question; skipping benchmark execution.", row_id)
                cfg.model = original_model
                writer.writerow({
                    "id": row_id,
                    "passed": "False",
                    "reason": "missing question in CSV row",
                    "model": row_model or original_model,
                    "system_prompt_file": system_prompt_file or "",
                    "eval_mode": eval_mode,
                    "question": "",
                    "output_text": "",
                    "score_correctness": "",
                    "score_reasoning": "",
                    "score_efficiency": "",
                    "score_total": "",
                    "mcp_call_count": "",
                    "queries": "",
                })
                continue

            req = RunRequest(
                user_prompt=question,
                system_prompt_file=system_prompt_file,
            )
            res = run_once(cfg, req)

            cfg.model = original_model
            
            exp, judge_spec = parse_expected(row)
            
            # Use appropriate evaluator
            if judge_spec is not None:
                ev = evaluate_llm_judge(cfg, res, judge_spec, req.user_prompt)
            else:
                ev = evaluate(res, exp)

            # Debug-print MCP trace per row when log level is DEBUG
            if bench_logger.isEnabledFor(logging.DEBUG):
                meta = getattr(res, "metadata", {}) if res else {}
                trace = None
                if isinstance(meta, dict):
                    trace = meta.get("mcp_trace") or meta.get("mcp_traces")
                if trace:
                    try:
                        trace_str = json.dumps(trace, ensure_ascii=False, indent=2)
                    except Exception:
                        trace_str = str(trace)
                    bench_logger.debug("MCP trace for id=%s:\n%s", row.get("id") or "", trace_str)

            details = ev.details or {}
            scores = details.get("scores", {}) if isinstance(details, dict) else {}
            meta = getattr(res, "metadata", {}) if res else {}
            trace = meta.get("mcp_trace", {}) if isinstance(meta, dict) else {}
            queries_list = trace.get("queries") or []
            
            writer.writerow({
                "id": row.get("id") or "",
                "passed": str(ev.passed),
                "reason": ev.reason or "",
                "model": res.model or "",
                "system_prompt_file": req.system_prompt_file or "",
                "eval_mode": row.get("eval_mode") or "",
                "question": req.user_prompt,
                "output_text": res.output_text,
                "score_correctness": scores.get("correctness", ""),
                "score_reasoning": scores.get("reasoning", ""),
                "score_efficiency": scores.get("efficiency", ""),
                "score_total": scores.get("weighted_total", ""),
                "mcp_call_count": trace.get("call_count", ""),
                "queries": "|".join(str(q) for q in queries_list[:10]),
            })

    return results_csv