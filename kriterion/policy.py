from __future__ import annotations

import json
import subprocess
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from .evaluators import percentile
from .schemas import DecisionRecord, DecisionStatus, EvidenceRecord, QualificationSpec, Status
from .util import command_available, file_hash, utc_now, write_json

POLICY_ID = "qualification-admission-v1"


def evaluate(spec: QualificationSpec, evidence: list[EvidenceRecord], policy_path: Path | None = None) -> DecisionRecord:
    policy_source = policy_path or Path("cedar/policies.cedar")
    attributes, failed_conditions, reason_codes = derive_policy_attributes(spec, evidence)
    policy_hash = file_hash(policy_source) if policy_source.exists() else "sha256:policy-file-missing"
    decision, cedar_error = _cedar_authorize(policy_source, attributes)
    repeated_decisions: list[str] = []
    cedar_consistency: float | None = None
    if cedar_error is None:
        repeated_decisions, cedar_consistency = cedar_decision_consistency(policy_source, attributes, repetitions=5)
    if cedar_error:
        decision = DecisionStatus.BLOCK
        failed_conditions.append("cedar: actual Cedar evaluation unavailable")
        reason_codes.append("CEDAR_UNAVAILABLE_FAIL_CLOSED")

    return DecisionRecord(
        decision_id="dec_" + uuid.uuid4().hex[:16],
        qualification_run_id=evidence[0].qualification_run_id if evidence else "run_missing",
        policy_id=POLICY_ID,
        policy_hash=policy_hash,
        decision=decision,
        evaluated_attributes={
            **attributes,
            "cedar_error": cedar_error,
            "cedar_cli": "REAL" if cedar_error is None else "UNAVAILABLE",
            "cedar_repeated_decisions": repeated_decisions,
            "cedar_consistency": cedar_consistency,
            "cedar_repetitions": len(repeated_decisions),
            "cedar_consistency_method": "same immutable evidence-derived attributes through cedar authorize",
        },
        failed_conditions=failed_conditions,
        reason_codes=sorted(set(reason_codes)),
        timestamp_utc=utc_now(),
    )


def derive_policy_attributes(spec: QualificationSpec, evidence: list[EvidenceRecord]) -> tuple[dict[str, Any], list[str], list[str]]:
    failed_conditions: list[str] = []
    reason_codes: list[str] = []
    by_requirement: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for item in evidence:
        by_requirement[item.requirement_id].append(item)

    attributes: dict[str, Any] = {
        "mandatory_evidence_complete": True,
        "no_mandatory_failures": True,
        "no_forbidden_action_violations": True,
        "artifact_pass": False,
        "license_pass": False,
        "runtime_within_threshold": False,
        "sandbox_pass": "sandbox" not in spec.requirements,
        "mandatory_requirement_pass_rate": None,
    }
    mandatory_passes = 0
    mandatory_total = 0
    for requirement_id, requirement in spec.requirements.items():
        if not requirement.mandatory:
            continue
        mandatory_total += 1
        records = by_requirement.get(requirement_id, [])
        if not records:
            attributes["mandatory_evidence_complete"] = False
            attributes["no_mandatory_failures"] = False
            failed_conditions.append(f"{requirement_id}: missing mandatory evidence")
            reason_codes.append("MANDATORY_EVIDENCE_MISSING")
            continue
        invalid = [item for item in records if item.status in {Status.ERROR, Status.INSUFFICIENT_EVIDENCE, Status.SKIPPED}]
        fails = [item for item in records if item.status == Status.FAIL]
        valid = [item for item in records if item.status in {Status.PASS, Status.FAIL}]
        if invalid or fails:
            attributes["no_mandatory_failures"] = False
            code = (invalid[0].status.value if invalid else "FAIL")
            failed_conditions.append(f"{requirement_id}: mandatory evidence has {code}")
            reason_codes.append(f"{requirement_id.upper()}_{code}")
        if requirement.minimum_pass_rate is not None:
            pass_rate = sum(1 for item in valid if item.status == Status.PASS) / len(valid) if valid else 0.0
            attributes[f"{requirement_id}_pass_rate"] = pass_rate
            if pass_rate >= requirement.minimum_pass_rate and not invalid:
                mandatory_passes += 1
            else:
                attributes["no_mandatory_failures"] = False
                failed_conditions.append(f"{requirement_id}: pass rate {pass_rate:.3f} < threshold {requirement.minimum_pass_rate:.3f}")
                reason_codes.append(f"{requirement_id.upper()}_THRESHOLD_FAILED")
        elif records and all(item.status == Status.PASS for item in records):
            mandatory_passes += 1

    attributes["mandatory_requirement_pass_rate"] = mandatory_passes / mandatory_total if mandatory_total else None
    attributes["artifact_pass"] = _all_pass(by_requirement.get("artifact", []))
    attributes["license_pass"] = _all_pass(by_requirement.get("license", []))
    attributes["sandbox_pass"] = _all_pass(by_requirement.get("sandbox", [])) if "sandbox" in spec.requirements else True
    p95_latency = percentile([item.duration_ms for item in evidence], 95)
    attributes["p95_latency_ms"] = p95_latency
    max_latency = spec.requirements["runtime"].maximum_p95_latency_ms or 0
    attributes["runtime_within_threshold"] = p95_latency <= max_latency
    if not attributes["runtime_within_threshold"]:
        failed_conditions.append(f"runtime: p95 latency {p95_latency} > threshold {max_latency}")
        reason_codes.append("RUNTIME_THRESHOLD_FAILED")
    forbidden = [item for item in evidence if item.requirement_id == "tool_policy" and item.status == Status.FAIL]
    attributes["no_forbidden_action_violations"] = not forbidden
    return attributes, failed_conditions, reason_codes


def _cedar_authorize(policy_path: Path, attributes: dict[str, Any]) -> tuple[DecisionStatus, str | None]:
    if not command_available("cedar"):
        return DecisionStatus.BLOCK, "cedar CLI not found on PATH"
    request_path = Path("artifacts/cedar/request.json")
    entities_path = Path("artifacts/cedar/entities.json")
    write_json(request_path, {"principal": "Kriterion::Run::\"current\"", "action": "Kriterion::Action::\"admit\"", "resource": "Kriterion::Workload::\"current\"", "context": attributes})
    write_json(entities_path, [])
    completed = subprocess.run(
        ["cedar", "authorize", "--policies", str(policy_path), "--entities", str(entities_path), "--request", str(request_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr).lower()
    if completed.returncode != 0:
        return DecisionStatus.BLOCK, output[-500:] or f"cedar exited {completed.returncode}"
    if "allow" in output or "permit" in output:
        return DecisionStatus.ADMIT, None
    return DecisionStatus.BLOCK, None


def cedar_decision_consistency(
    policy_path: Path,
    attributes: dict[str, Any],
    repetitions: int = 5,
) -> tuple[list[str], float | None]:
    decisions: list[str] = []
    for _ in range(repetitions):
        decision, error = _cedar_authorize(policy_path, attributes)
        if error:
            return decisions, None
        decisions.append(decision.value)
    if not decisions:
        return decisions, None
    first = decisions[0]
    return decisions, sum(1 for item in decisions if item == first) / len(decisions)


def _all_pass(records: list[EvidenceRecord]) -> bool:
    return bool(records) and all(item.status == Status.PASS for item in records)
