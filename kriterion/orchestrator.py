from __future__ import annotations

import uuid
from pathlib import Path

from .agent import generate_spec, generate_spec_from_description
from .finch import run_in_finch
from .metrics import coverage, runtime_summary, security_metrics, test_summary
from .policy import evaluate
from .schemas import ModelRecord, RunRecord, to_dict
from .storage import LocalOpenSearchStore, runtime_store
from .util import ensure_dir, environment, read_json, stable_hash, utc_now, write_json


def qualify(
    model: ModelRecord,
    workload_description: str,
    artifact_root: Path = Path("artifacts"),
    store: LocalOpenSearchStore | None = None,
    allow_local_evaluator: bool = False,
    allow_strands_fallback: bool = False,
) -> RunRecord:
    store = store or runtime_store(artifact_root / "store")
    started = utc_now()
    run_id = "run_" + uuid.uuid4().hex[:12]
    spec = generate_spec_from_description(workload_description, allow_fallback=allow_strands_fallback)
    evidence = run_in_finch(run_id, model, spec, artifact_root, allow_local_fallback=allow_local_evaluator)
    decision = evaluate(spec, evidence)
    completed = utc_now()

    evidence_path = artifact_root / "evidence" / f"{run_id}.jsonl"
    ensure_dir(evidence_path.parent)
    with evidence_path.open("w", encoding="utf-8") as handle:
        for item in evidence:
            handle.write(__import__("json").dumps(to_dict(item), sort_keys=True) + "\n")

    manifest = {
        "qualification_run_id": run_id,
        "model_id": model.model_id,
        "model_revision": model.revision,
        "artifact_hash": model.artifact_hash,
        "workload_id": spec.workload_id,
        "spec_id": spec.spec_id,
        "spec_version": spec.version,
        "test_suite_version": "1.0.0",
        "policy_version": spec.policy_version,
        "environment": environment(),
        "random_seed": 0,
        "thresholds": spec.thresholds,
        "fixture_hashes": [item.reproducibility["fixture_hash"] for item in evidence],
        "evaluator_environment": [
            item.reproducibility for item in evidence if item.requirement_id == "evaluator_environment"
        ],
    }
    manifest_path = artifact_root / "manifests" / f"{run_id}.json"
    write_json(manifest_path, manifest)
    spec_path = artifact_root / "specifications" / f"{run_id}.json"
    write_json(spec_path, to_dict(spec))

    run = RunRecord(
        qualification_run_id=run_id,
        started_at_utc=started,
        completed_at_utc=completed,
        model=to_dict(model),
        workload={
            "workload_id": spec.workload_id,
            "workload_name": spec.workload_name,
            "workload_description": spec.workload_description,
            "spec_id": spec.spec_id,
            "spec_version": spec.version,
        },
        environment=manifest["environment"],
        test_summary=test_summary(evidence),
        security_metrics=security_metrics(evidence),
        coverage=coverage(spec, evidence),
        runtime=runtime_summary(evidence),
        sandbox={
            "executions": sum(1 for item in evidence if item.sandbox.required),
            "violations_detected": sum(1 for item in evidence if item.requirement_id == "sandbox" and item.status.value != "PASS"),
            "containment_test_pass_rate": _pass_rate([item for item in evidence if item.requirement_id == "sandbox"]),
        },
        cedar={
            "policy_id": decision.policy_id,
            "decision": decision.decision.value,
            "reason_codes": decision.reason_codes,
        },
        decision={"status": decision.decision.value, "fail_closed": decision.decision.value == "BLOCK"},
        evidence_path=str(evidence_path),
        manifest_path=str(manifest_path),
    )

    write_json(artifact_root / "runs" / f"{run_id}.json", to_dict(run))
    write_json(artifact_root / "decisions" / f"{run_id}.json", to_dict(decision))
    _write_report(artifact_root / "reports" / f"{run_id}.md", run, decision.failed_conditions)

    store.index("kriterion-models", to_dict(model), model.model_id)
    store.index(
        "kriterion-workloads",
        {"workload_id": spec.workload_id, "name": spec.workload_name, "description": spec.workload_description},
        spec.workload_id,
    )
    store.index("kriterion-specifications", to_dict(spec), spec.spec_id)
    store.index("kriterion-runs", to_dict(run), run_id)
    store.index("kriterion-decisions", to_dict(decision), decision.decision_id)
    for item in evidence:
        store.index("kriterion-evidence", to_dict(item), item.evidence_id)
    fixture = read_json(Path("fixtures/security-fixtures-v1.json"))
    store.index(
        "kriterion-test-fixtures",
        {
            "dataset_id": fixture["dataset_id"],
            "version": fixture["version"],
            "path": "fixtures/security-fixtures-v1.json",
            "hash": stable_hash(fixture),
            "cases": fixture["cases"],
        },
        fixture["dataset_id"],
    )

    return run


def qualify_template(
    model: ModelRecord,
    workload_id: str,
    artifact_root: Path = Path("artifacts"),
    store: LocalOpenSearchStore | None = None,
    allow_local_evaluator: bool = True,
    allow_strands_fallback: bool = True,
) -> RunRecord:
    spec = generate_spec(workload_id)
    return qualify(model, spec.workload_description, artifact_root, store, allow_local_evaluator, allow_strands_fallback)


def _pass_rate(items) -> float | None:
    if not items:
        return None
    return sum(1 for item in items if item.status.value == "PASS") / len(items)


def _write_report(path: Path, run: RunRecord, failed_conditions: list[str]) -> None:
    ensure_dir(path.parent)
    lines = [
        f"# Qualification Report {run.qualification_run_id}",
        "",
        f"Decision: **{run.decision['status']}**",
        f"Model: `{run.model['model_id']}`",
        f"Workload: `{run.workload['workload_id']}`",
        "",
        "## Failed Conditions",
    ]
    lines.extend([f"- {condition}" for condition in failed_conditions] or ["- None"])
    lines.extend(["", "## Artifacts", f"- Evidence: `{run.evidence_path}`", f"- Manifest: `{run.manifest_path}`"])
    ensure_dir(path.parent)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
