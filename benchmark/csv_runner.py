import csv
import json
from pathlib import Path
from typing import Dict, Any, Iterable, Tuple
from app.config import AppConfig
from app.runner import run_once
from app.types import RunRequest, ExpectedSpec
from app.evaluator import evaluate

# CSV columns (suggested):
# id, prompt, system_prompt_file, eval_mode, expected
# where expected can be JSON (for equals_json/json_subset) or plain text/regex depending on eval_mode.

def load_rows(csv_path: Path) -> Iterable[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row

def parse_expected(row: Dict[str, str]) -> ExpectedSpec:
    mode = (row.get("eval_mode") or "").strip()
    raw = row.get("expected") or ""
    if mode in ("equals_json", "json_subset"):
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if mode == "equals_json":
            return ExpectedSpec(equals_json=data)
        return ExpectedSpec(json_subset=data)
    if mode == "exact_text":
        return ExpectedSpec(exact_text=raw)
    if mode == "regex":
        return ExpectedSpec(regex=raw)
    return ExpectedSpec()  # no criterion -> will fail explicitly

def run_benchmark(cfg: AppConfig, csv_file: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    results_csv = out_dir / "results.csv"

    with results_csv.open("w", encoding="utf-8", newline="") as f_out:
        writer = csv.DictWriter(
            f_out,
            fieldnames=[
                "id","passed","reason","model","system_prompt_file","eval_mode","prompt","output_text"
            ],
        )
        writer.writeheader()

        for row in load_rows(csv_file):
            req = RunRequest(
                user_prompt=row.get("prompt") or "",
                system_prompt_file=row.get("system_prompt_file") or None,
            )
            res = run_once(cfg, req)
            exp = parse_expected(row)
            ev = evaluate(res, exp)

            writer.writerow({
                "id": row.get("id") or "",
                "passed": str(ev.passed),
                "reason": ev.reason or "",
                "model": res.model or "",
                "system_prompt_file": req.system_prompt_file or "",
                "eval_mode": row.get("eval_mode") or "",
                "prompt": req.user_prompt,
                "output_text": res.output_text,
            })

    return results_csv