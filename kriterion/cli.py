from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import registered_models
from .agent import example_workload_prompts
from .finch import evaluator_run
from .metrics import aggregate_runs
from .orchestrator import qualify, qualify_template


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kriterion")
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("qualify")
    q.add_argument("--model-id", default="hf_tiny_gpt2_local")
    q.add_argument("--workload-description")
    q.add_argument("--workload-file")
    q.add_argument("--artifacts", default="artifacts")
    q.add_argument("--allow-local-evaluator", action="store_true", help="developer mode: bypass Finch when it is unavailable")
    q.add_argument("--allow-strands-fallback", action="store_true", help="developer mode: use heuristic workload analysis if Strands is unavailable")

    demo = sub.add_parser("demo")
    demo.add_argument("--artifacts", default="artifacts")
    demo.add_argument("--allow-local-evaluator", action="store_true")
    demo.add_argument("--allow-strands-fallback", action="store_true", default=True)
    demo.add_argument("--repetitions", type=int, default=2)

    bench = sub.add_parser("benchmark")
    bench.add_argument("--artifacts", default="artifacts")
    bench.add_argument("--allow-local-evaluator", action="store_true")
    bench.add_argument("--allow-strands-fallback", action="store_true")
    bench.add_argument("--repetitions", type=int, default=2)
    bench.add_argument(
        "--fixture-model",
        action="store_true",
        help="use the deterministic fixture model (model_demo_fixture_001) instead of hf_tiny_gpt2_local; for development/CI only, not valid for admission benchmarks",
    )

    evaluator = sub.add_parser("evaluator-run")
    evaluator.add_argument("--input", required=True)
    evaluator.add_argument("--output", required=True)

    metrics = sub.add_parser("metrics")
    metrics_sub = metrics.add_subparsers(dest="metrics_command", required=True)
    aggregate = metrics_sub.add_parser("aggregate")
    aggregate.add_argument("--runs", default="artifacts/runs")
    aggregate.add_argument("--output", default="artifacts/metrics/summary.json")

    args = parser.parse_args(argv)
    if args.command == "qualify":
        description = _workload_description(args.workload_description, args.workload_file)
        run = qualify(
            _find_model(args.model_id),
            description,
            Path(args.artifacts),
            allow_local_evaluator=args.allow_local_evaluator,
            allow_strands_fallback=args.allow_strands_fallback,
        )
        print(json.dumps({"run_id": run.qualification_run_id, "decision": run.decision["status"]}, indent=2))
    elif args.command == "demo":
        model = _find_model("model_demo_fixture_001")
        runs = []
        for _ in range(max(1, args.repetitions)):
            for text in example_workload_prompts().values():
                runs.append(
                    qualify(
                        model,
                        text,
                        Path(args.artifacts),
                        allow_local_evaluator=args.allow_local_evaluator,
                        allow_strands_fallback=args.allow_strands_fallback,
                    )
                )
        _print_runs(runs)
    elif args.command == "benchmark":
        model_id = "model_demo_fixture_001" if args.fixture_model else "hf_tiny_gpt2_local"
        model = _find_model(model_id)
        runs = [
            qualify(
                model,
                text,
                Path(args.artifacts),
                allow_local_evaluator=args.allow_local_evaluator,
                allow_strands_fallback=args.allow_strands_fallback,
            )
            for text in example_workload_prompts().values()
        ]
        summary = aggregate_runs(Path(args.artifacts) / "runs", Path(args.artifacts) / "metrics" / "summary.json")
        _print_runs(runs)
        print("Metrics:", str(Path(args.artifacts) / "metrics" / "summary.json"))
        print(json.dumps(summary["sample_sizes"], indent=2, sort_keys=True))
    elif args.command == "evaluator-run":
        evaluator_run(Path(args.input), Path(args.output))
    elif args.command == "metrics" and args.metrics_command == "aggregate":
        summary = aggregate_runs(Path(args.runs), Path(args.output))
        print(json.dumps(summary, indent=2, sort_keys=True))


def _workload_description(inline: str | None, path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    if inline:
        return inline
    raise SystemExit("Provide --workload-description or --workload-file")


def _find_model(model_id: str):
    for model in registered_models():
        if model.model_id == model_id:
            return model
    raise SystemExit(f"Unknown model_id: {model_id}")


def _print_runs(runs) -> None:
    print("Kriterion run complete.")
    for run in runs:
        print(f"{run.model['model_id']} + {run.workload['workload_name']} -> {run.decision['status']} ({run.qualification_run_id})")