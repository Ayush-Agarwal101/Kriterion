from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .adapters import adapter_for_model
from .config import finch_ollama_base_url
from .evaluators import run_evaluators
from .finch_bridge import finch_available, run_finch, run_finch_with_volume
from .schemas import EvidenceRecord, ModelRecord, QualificationSpec, Status, to_dict
from .util import command_available, ensure_dir, read_json, write_json


def _evaluator_image_tag() -> str:
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
    result = run_finch(["image", "inspect", tag], cwd=Path.cwd())
    return result.returncode == 0


def _finch_is_available() -> bool:
    # command_available remains the compatibility seam used by the existing
    # tests. In WSL, the bridge supplies availability through Windows Finch.
    return command_available("finch") or finch_available()


def run_in_finch(
    run_id: str,
    model: ModelRecord,
    spec: QualificationSpec,
    artifact_root: Path,
    allow_local_fallback: bool = False,
) -> list[EvidenceRecord]:
    if os.environ.get("KRITERION_IN_FINCH") == "1":
        return run_evaluators(run_id, model, spec, adapter_for_model(model))

    if not _finch_is_available():
        if allow_local_fallback:
            return [_finch_local_fallback(run_id, model, spec)] + run_evaluators(
                run_id, model, spec, adapter_for_model(model)
            )
        return [_finch_unavailable(
            run_id, model, spec, "Finch could not be invoked from this environment."
        )]

    io_root = ensure_dir(artifact_root / "finch" / run_id)
    input_path = io_root / "input.json"
    output_path = io_root / "evidence.jsonl"

    write_json(
        input_path,
        {"run_id": run_id, "model": to_dict(model), "spec": to_dict(spec)},
    )

    image_tag = _evaluator_image_tag()
    if not _image_exists(image_tag):
        build = run_finch(
            ["build", "-t", image_tag, "-f", "finch/Dockerfile", "."],
            cwd=Path.cwd(),
        )
        if build.returncode != 0:
            return [_finch_unavailable(
                run_id, model, spec,
                "Finch build failed: " + (build.stdout + build.stderr)[-500:],
            )]

    # The endpoint is runtime configuration, never baked into the image.
    # For the Windows Finch/WSL setup this should be the Windows-host-reachable
    # Ollama address, e.g. http://192.168.0.1:11434.
    ollama_url = finch_ollama_base_url()

    run = run_finch_with_volume(
        [
            "run",
            "--rm",
            "-e",
            "KRITERION_IN_FINCH=1",
            "-e",
            f"KRITERION_OLLAMA_BASE_URL={ollama_url}",
            "-v",
            "",
            image_tag,
            "evaluator-run",
            "--input",
            "/kriterion-io/input.json",
            "--output",
            "/kriterion-io/evidence.jsonl",
        ],
        cwd=Path.cwd(),
        host_volume_path=io_root,
        container_volume_path="/kriterion-io",
    )

    if run.returncode != 0 or not output_path.exists():
        return [_finch_unavailable(
            run_id, model, spec,
            "Finch evaluator run failed: " + (run.stdout + run.stderr)[-500:],
        )]

    return [_finch_pass(run_id, model, spec, image_tag)] + _load_evidence(output_path)


def evaluator_run(input_path: Path, output_path: Path) -> None:
    payload = read_json(input_path)
    from .schemas import ModelRecord, QualificationSpec

    model = ModelRecord(**payload["model"])
    spec = QualificationSpec(**payload["spec"])
    evidence = run_evaluators(
        payload["run_id"], model, spec, adapter_for_model(model)
    )
    ensure_dir(output_path.parent)
    with output_path.open("w", encoding="utf-8") as handle:
        for item in evidence:
            handle.write(json.dumps(to_dict(item), sort_keys=True) + "\n")


def _load_evidence(path: Path) -> list[EvidenceRecord]:
    from .schemas import PYDANTIC_AVAILABLE, SandboxRecord

    records: list[EvidenceRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            data = json.loads(line)
            if not PYDANTIC_AVAILABLE and isinstance(data.get("sandbox"), dict):
                data["sandbox"] = SandboxRecord(**data["sandbox"])
            records.append(EvidenceRecord(**data))
    return records


def _finch_unavailable(run_id: str, model: ModelRecord, spec: QualificationSpec, detail: str) -> EvidenceRecord:
    from .evaluators import _evidence
    from .schemas import SandboxRecord

    return _evidence(
        run_id, model, spec, "INFRA-FINCH", "finch_evaluator_environment",
        "FINCH-001", "evaluator_environment", "infrastructure",
        "Evaluator suite executes inside Finch container", detail,
        Status.INSUFFICIENT_EVIDENCE, True, score=0.0, threshold=1.0,
        sandbox=SandboxRecord(
            required=False, used=False, provider="finch",
            available=False, detail=detail,
        ),
        error=detail,
    )


def _finch_pass(run_id: str, model: ModelRecord, spec: QualificationSpec, image_tag: str) -> EvidenceRecord:
    from .evaluators import _evidence
    from .schemas import SandboxRecord

    return _evidence(
        run_id, model, spec, "INFRA-FINCH", "finch_evaluator_environment",
        "FINCH-001", "evaluator_environment", "infrastructure",
        "Evaluator suite executes inside Finch container",
        f"Finch image {image_tag} built and evaluator completed.",
        Status.PASS, True, score=1.0, threshold=1.0,
        sandbox=SandboxRecord(
            required=False, used=True, provider="finch",
            available=True, detail=image_tag,
        ),
        extra_repro={"finch_image": image_tag},
    )


def _finch_local_fallback(run_id: str, model: ModelRecord, spec: QualificationSpec) -> EvidenceRecord:
    from .evaluators import _evidence
    from .schemas import SandboxRecord

    return _evidence(
        run_id, model, spec, "INFRA-FINCH", "finch_evaluator_environment",
        "FINCH-DEV-FALLBACK", "evaluator_environment", "infrastructure",
        "Evaluator suite executes inside Finch container",
        "Developer fallback executed evaluators locally; not valid for admission benchmark.",
        Status.INSUFFICIENT_EVIDENCE, True, score=0.0, threshold=1.0,
        sandbox=SandboxRecord(
            required=False, used=False, provider="finch",
            available=False, detail="developer fallback",
        ),
        error="developer local evaluator fallback",
    )
