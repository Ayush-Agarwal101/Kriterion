from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .adapters import adapter_for_model
from .evaluators import run_evaluators
from .schemas import EvidenceRecord, ModelRecord, QualificationSpec, Status, to_dict
from .util import command_available, ensure_dir, read_json, write_json


def _evaluator_image_tag() -> str:
    """
    Compute a content-addressed tag for the evaluator image.

    Only files that determine the image contents are hashed: the Dockerfile,
    the evaluator requirements file, all kriterion source files, Cedar
    policies, and test fixtures.

    Model identity, workload description, and all other run-time inputs are
    intentionally excluded — changing them must NOT trigger a rebuild.
    """
    candidates: list[Path] = [
        Path("finch/Dockerfile"),
        Path("finch/requirements-evaluator.txt"),
    ]
    for root_dir, pattern in [
        (Path("kriterion"), "**/*.py"),
        (Path("cedar"), "**/*.cedar"),
        (Path("fixtures"), "**/*.json"),
    ]:
        if root_dir.is_dir():
            candidates.extend(sorted(root_dir.glob(pattern)))

    h = hashlib.sha256()
    for p in candidates:
        if p.exists():
            h.update(str(p).encode())
            h.update(b"\x00")
            h.update(p.read_bytes())
    return f"kriterion-evaluator:{h.hexdigest()[:12]}"


def _image_exists(tag: str) -> bool:
    """Return True if an image with this exact tag is already in the local store."""
    result = subprocess.run(
        ["finch", "image", "inspect", tag], capture_output = True, text = True, encoding = "utf-8", errors = "replace",
        check = False,
    )
    return result.returncode == 0


def run_in_finch(
    run_id: str,
    model: ModelRecord,
    spec: QualificationSpec,
    artifact_root: Path,
    allow_local_fallback: bool = False,
) -> list[EvidenceRecord]:
    if os.environ.get("KRITERION_IN_FINCH") == "1":
        return run_evaluators(run_id, model, spec, adapter_for_model(model))
    if not command_available("finch"):
        if allow_local_fallback:
            return [_finch_local_fallback(run_id, model, spec)] + run_evaluators(run_id, model, spec, adapter_for_model(model))
        return [_finch_unavailable(run_id, model, spec, "Finch binary was not found on PATH.")]

    io_root = ensure_dir(artifact_root / "finch" / run_id)
    input_path = io_root / "input.json"
    output_path = io_root / "evidence.jsonl"

    # Model and workload are runtime inputs written to the mounted volume.
    # They are never baked into the image.
    write_json(input_path, {"run_id": run_id, "model": to_dict(model), "spec": to_dict(spec)})

    # Compute a content-addressed tag so the image is rebuilt only when the
    # Dockerfile, evaluator deps, source code, policies, or fixtures change.
    # Changing the model or workload does not affect this tag.
    image_tag = _evaluator_image_tag()
    if not _image_exists(image_tag):
        build = subprocess.run(
            ["finch", "build", "-t", image_tag, "-f", "finch/Dockerfile", "."], capture_output = True, text = True,
            encoding = "utf-8", errors = "replace", check = False,
        )
        if build.returncode != 0:
            return [_finch_unavailable(run_id, model, spec, "Finch build failed: " + (build.stdout + build.stderr)[-500:])]

    run = subprocess.run(
        [
            "finch",
            "run",
            "--rm",
            "-e",
            "KRITERION_IN_FINCH=1",
            "-v",
            f"{io_root}:/kriterion-io",
            image_tag,
            "evaluator-run",
            "--input",
            "/kriterion-io/input.json",
            "--output",
            "/kriterion-io/evidence.jsonl",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0 or not output_path.exists():
        return [_finch_unavailable(run_id, model, spec, "Finch evaluator run failed: " + (run.stdout + run.stderr)[-500:])]
    return [_finch_pass(run_id, model, spec, image_tag)] + _load_evidence(output_path)


def evaluator_run(input_path: Path, output_path: Path) -> None:
    payload = read_json(input_path)
    from .schemas import ModelRecord, QualificationSpec

    model = ModelRecord(**payload["model"])
    spec = QualificationSpec(**payload["spec"])
    evidence = run_evaluators(payload["run_id"], model, spec, adapter_for_model(model))
    ensure_dir(output_path.parent)
    with output_path.open("w", encoding="utf-8") as handle:
        for item in evidence:
            handle.write(json.dumps(to_dict(item), sort_keys=True) + "\n")


def _load_evidence(path: Path) -> list[EvidenceRecord]:
    from .schemas import PYDANTIC_AVAILABLE, EvidenceRecord, SandboxRecord

    records: list[EvidenceRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            data = json.loads(line)
            # Pydantic v2 coerces nested dicts to model instances automatically.
            # On the dataclass path there is no coercion, so construct SandboxRecord
            # explicitly when the field arrives as a plain dict.
            if not PYDANTIC_AVAILABLE and isinstance(data.get("sandbox"), dict):
                data["sandbox"] = SandboxRecord(**data["sandbox"])
            records.append(EvidenceRecord(**data))
    return records


def _finch_unavailable(run_id: str, model: ModelRecord, spec: QualificationSpec, detail: str) -> EvidenceRecord:
    from .evaluators import _evidence
    from .schemas import SandboxRecord

    return _evidence(
        run_id,
        model,
        spec,
        "INFRA-FINCH",
        "finch_evaluator_environment",
        "FINCH-001",
        "evaluator_environment",
        "infrastructure",
        "Evaluator suite executes inside Finch container",
        detail,
        Status.INSUFFICIENT_EVIDENCE,
        True,
        score=0.0,
        threshold=1.0,
        sandbox=SandboxRecord(required=False, used=False, provider="finch", available=False, detail=detail),
        error=detail,
    )


def _finch_pass(run_id: str, model: ModelRecord, spec: QualificationSpec, image_tag: str) -> EvidenceRecord:
    from .evaluators import _evidence
    from .schemas import SandboxRecord

    return _evidence(
        run_id,
        model,
        spec,
        "INFRA-FINCH",
        "finch_evaluator_environment",
        "FINCH-001",
        "evaluator_environment",
        "infrastructure",
        "Evaluator suite executes inside Finch container",
        f"Finch image {image_tag} built and evaluator completed.",
        Status.PASS,
        True,
        score=1.0,
        threshold=1.0,
        sandbox=SandboxRecord(required=False, used=True, provider="finch", available=True, detail=image_tag),
        extra_repro={"finch_image": image_tag},
    )


def _finch_local_fallback(run_id: str, model: ModelRecord, spec: QualificationSpec) -> EvidenceRecord:
    from .evaluators import _evidence
    from .schemas import SandboxRecord

    return _evidence(
        run_id,
        model,
        spec,
        "INFRA-FINCH",
        "finch_evaluator_environment",
        "FINCH-DEV-FALLBACK",
        "evaluator_environment",
        "infrastructure",
        "Evaluator suite executes inside Finch container",
        "Developer fallback executed evaluators locally; not valid for admission benchmark.",
        Status.INSUFFICIENT_EVIDENCE,
        True,
        score=0.0,
        threshold=1.0,
        sandbox=SandboxRecord(required=False, used=False, provider="finch", available=False, detail="developer fallback"),
        error="developer local evaluator fallback",
    )
