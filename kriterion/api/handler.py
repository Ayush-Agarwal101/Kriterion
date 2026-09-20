from __future__ import annotations

import json
from pathlib import Path

from kriterion.model_registry import ModelNotFoundError, resolve_model
from kriterion.orchestrator import qualify


def _json_response(status_code: int, payload: dict):
    return {"statusCode": status_code, "headers": {"content-type": "application/json"}, "body": json.dumps(payload)}


def handle(event, context):
    body = json.loads(event.get("body") or "{}")
    model_id = body.get("model_id", "hf_tiny_gpt2_local")
    workload_description = body.get("workload_description")
    if not workload_description:
        return _json_response(400, {"error": "workload_description is required"})
    try:
        model = resolve_model(model_id)
    except ModelNotFoundError as exc:
        return _json_response(404, {"error": str(exc), "model_id": exc.model_id})
    run = qualify(
        model,
        workload_description,
        Path("artifacts"),
        allow_local_evaluator=bool(body.get("allow_local_evaluator", False)),
        allow_strands_fallback=bool(body.get("allow_strands_fallback", False)),
    )
    return _json_response(200, {"run_id": run.qualification_run_id, "decision": run.decision["status"]})
