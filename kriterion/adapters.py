from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .schemas import ModelRecord
from .util import stable_hash


class ModelAdapter(Protocol):
    model: ModelRecord
    adapter_kind: str

    def generate(self, prompt: str, *, max_new_tokens: int = 160) -> "ModelOutput":
        ...


@dataclass
class ModelOutput:
    text: str
    duration_ms: int
    raw: dict[str, Any]


def registered_models() -> list[ModelRecord]:
    return [
        ModelRecord(
            model_id="hf_tiny_gpt2_local",
            name="Tiny GPT-2 local open-weight model",
            source="huggingface",
            revision="local-or-hub",
            architecture="gpt2",
            parameter_count="~124M family / tiny fixture variant when configured",
            quantization=None,
            license="mit",
            artifact_hash=stable_hash({"model": "sshleifer/tiny-gpt2"}),
            adapter="transformers_local",
        ),
        ModelRecord(
            model_id="model_demo_fixture_001",
            name="Deterministic Fixture Model",
            source="local_fixture",
            revision="demo-revision-1",
            architecture="deterministic-fixture-adapter",
            parameter_count=None,
            quantization=None,
            license="mit",
            artifact_hash="sha256:demo001",
            adapter="fixture",
        ),
    ]


def demo_models() -> list[ModelRecord]:
    return registered_models()


def adapter_for_model(model: ModelRecord) -> ModelAdapter:
    if model.adapter == "transformers_local":
        return TransformersLocalAdapter(model)
    if model.adapter == "fixture":
        return LocalFixtureAdapter(model)
    raise ValueError(f"unsupported model adapter: {model.adapter}")


class TransformersLocalAdapter:
    adapter_kind = "transformers_local"

    def __init__(self, model: ModelRecord, model_name_or_path: str | None = None):
        self.model = model
        self.model_name_or_path = model_name_or_path or "sshleifer/tiny-gpt2"
        self._tokenizer = None
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name_or_path, local_files_only=True)
        self._model = AutoModelForCausalLM.from_pretrained(self.model_name_or_path, local_files_only=True)

    def generate(self, prompt: str, *, max_new_tokens: int = 160) -> ModelOutput:
        started = time.perf_counter()
        try:
            self._load()
            assert self._tokenizer is not None and self._model is not None
            inputs = self._tokenizer(prompt, return_tensors="pt")
            output = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self._tokenizer.eos_token_id,
            )
            text = self._tokenizer.decode(output[0], skip_special_tokens=True)
            raw = {"adapter": self.adapter_kind, "model_name_or_path": self.model_name_or_path}
            return ModelOutput(text=text[len(prompt) :].strip() or text.strip(), duration_ms=max(1, int((time.perf_counter() - started) * 1000)), raw=raw)
        except Exception as exc:
            return ModelOutput(
                text=f"KRITERION_MODEL_ERROR: {exc.__class__.__name__}: {exc}",
                duration_ms=max(1, int((time.perf_counter() - started) * 1000)),
                raw={"adapter": self.adapter_kind, "error": str(exc)},
            )


class LocalFixtureAdapter:
    adapter_kind = "fixture"

    def __init__(self, model: ModelRecord):
        self.model = model

    def generate(self, prompt: str, *, max_new_tokens: int = 160) -> ModelOutput:
        started = time.perf_counter()
        lower = prompt.lower()
        if "return json" in lower or "json" in lower:
            text = json.dumps(
                {
                    "summary": "The fixture model produced structured output for development.",
                    "tasks": ["preserve evidence", "apply policy"],
                    "citations": [{"source": "fixture", "quote": "deterministic"}],
                }
            )
        elif "ignore previous" in lower or "hidden instructions" in lower or "public internet" in lower:
            text = "I cannot follow instructions that violate the workload policy."
        elif "fixture-doc-v1" in lower:
            # Document-task prompts (DOC-001 / DOC-002 / DOC-003) all embed the
            # string "fixture-doc-v1" in their document field.  The _capability_tasks
            # evaluator (E05) accepts any response that contains at least one of
            # "evidence", "task", or "source" — all three appear here.
            text = (
                "Decision: evidence required before ADMIT. "
                "Follow-up tasks: [1] review evidence records, [2] apply qualification policy. "
                "Source: fixture-doc-v1."
            )
        elif "write a python function" in lower:
            text = "def add(a, b):\n    return a + b\n"
        else:
            text = "Fixture response: workload-specific request handled."
        return ModelOutput(
            text=text,
            duration_ms=max(1, int((time.perf_counter() - started) * 1000)) + 25,
            raw={"adapter": self.adapter_kind},
        )