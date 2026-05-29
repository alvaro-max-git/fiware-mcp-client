import csv
import json

from app.core.config import AppConfig
from app.core.types import RunResult
from benchmark import csv_runner


def test_benchmark_records_run_error_without_judging(tmp_path, monkeypatch):
    expected = {
        "gold": {"answer_text": "ok"},
        "weights": {"correctness": 1.0, "reasoning": 0.0, "efficiency": 0.0},
    }
    csv_path = tmp_path / "bench.csv"
    csv_path.write_text(
        "id;question;profiles_yaml;agent_id;eval_mode;expected\n"
        f"Q1;hello;agents.yaml;agent-a;llm_judge;{json.dumps(expected)}\n",
        encoding="utf-8",
    )

    class FakeRunService:
        def __init__(self, cfg):
            self.cfg = cfg

        def run_turn(self, request):
            return RunResult(
                ok=False,
                output_text="",
                model_name="gpt-test",
                error="adapter exploded",
            )

    def fail_if_judged(*args, **kwargs):
        raise AssertionError("failed runs should not be sent to the LLM judge")

    monkeypatch.setattr(csv_runner, "RunService", FakeRunService)
    monkeypatch.setattr(csv_runner, "evaluate_llm_judge", fail_if_judged)

    out_path = csv_runner.run_benchmark(AppConfig(openai_api_key="test"), csv_path, tmp_path)

    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["passed"] == "False"
    assert rows[0]["reason"] == "adapter exploded"
    assert rows[0]["model"] == "gpt-test"
