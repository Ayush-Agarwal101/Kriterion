from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from .handler import handle


def qualify_via_api(
    model_id: str,
    workload_description: str,
    allow_local_evaluator: bool = False,
    allow_strands_fallback: bool = False,
) -> dict[str, Any]:
    payload = {
        "model_id": model_id,
        "workload_description": workload_description,
        "allow_local_evaluator": allow_local_evaluator,
        "allow_strands_fallback": allow_strands_fallback,
    }
    api_url = os.environ.get("KRITERION_API_URL")
    if api_url:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            api_url.rstrip("/") + "/qualify",
            data=data,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    response = handle({"body": json.dumps(payload)}, None)
    body = json.loads(response["body"])
    if response["statusCode"] >= 400:
        raise RuntimeError(body.get("error", "qualification API failed"))
    return body
