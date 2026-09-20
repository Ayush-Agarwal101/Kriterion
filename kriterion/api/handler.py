from __future__ import annotations

import json
from pathlib import Path

from kriterion.adapters import demo_models
from kriterion.orchestrator import qualify


def handle(event, context):
    body = json.loads(event.get("body") or "{}")
    model_id = body.get("model_id", "hf_tiny_gpt2_local")
    workload_description = body.get("workload_description")
    if not workload_description:
        return {"statusCode": 400, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "workload_description is required"})}
    model = next(model for model in demo_models() if model.model_id == model_id)
    run = qualify(
        model,
        workload_description,
        Path("artifacts"),
        allow_local_evaluator=bool(body.get("allow_local_evaluator", False)),
        allow_strands_fallback=bool(body.get("allow_strands_fallback", False)),
    )
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"run_id": run.qualification_run_id, "decision": run.decision["status"]}),
    }
