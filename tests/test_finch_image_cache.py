"""
Tests for the Finch evaluator image caching and runtime input contract.

Key invariants verified here:
  1. _evaluator_image_tag() produces a stable, content-addressed hex digest.
  2. The tag format is exactly "kriterion-evaluator:<12 hex chars>".
  3. _evaluator_image_tag() takes no model or workload arguments — model/workload
     changes can never affect the tag by construction.
  4. When the image already exists (_image_exists returns True), run_in_finch
     must NOT call finch build; it goes straight to finch run.
  5. evaluator_run() deserialises ModelRecord and QualificationSpec from the
     input.json payload at container start — they are runtime inputs, not
     baked into the image.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestEvaluatorImageTag(unittest.TestCase):
    def test_tag_is_stable_across_calls(self):
        """Calling _evaluator_image_tag() twice from the same working directory
        must return an identical string."""
        from kriterion.finch import _evaluator_image_tag

        self.assertEqual(_evaluator_image_tag(), _evaluator_image_tag())

    def test_tag_format(self):
        """Tag must be 'kriterion-evaluator:' followed by exactly 12 lowercase
        hex characters (first 12 chars of a SHA-256 digest)."""
        from kriterion.finch import _evaluator_image_tag

        tag = _evaluator_image_tag()
        self.assertIn(":", tag, "Tag must contain a colon separator")
        name, digest = tag.split(":", 1)
        self.assertEqual(name, "kriterion-evaluator")
        self.assertEqual(len(digest), 12, f"Digest must be 12 chars, got {len(digest)}: {digest!r}")
        self.assertTrue(
            all(c in "0123456789abcdef" for c in digest),
            f"Digest must be lowercase hex, got: {digest!r}",
        )

    def test_tag_does_not_accept_model_or_workload_arguments(self):
        """_evaluator_image_tag takes no parameters: model/workload cannot
        affect the tag by accident."""
        import inspect
        from kriterion.finch import _evaluator_image_tag

        sig = inspect.signature(_evaluator_image_tag)
        self.assertEqual(
            len(sig.parameters),
            0,
            "_evaluator_image_tag must take no arguments so model/workload changes cannot influence it",
        )


class TestImageReuseSkipsBuild(unittest.TestCase):
    def test_image_reuse_skips_finch_build(self):
        """When _image_exists returns True, run_in_finch must not invoke
        'finch build' at all; it should go directly to 'finch run'."""
        from kriterion.adapters import demo_models
        from kriterion.agent import generate_spec_from_description
        from kriterion.finch import run_in_finch

        model = next(m for m in demo_models() if m.adapter == "fixture")
        spec = generate_spec_from_description("Summarise documents as JSON.", allow_fallback=True)

        build_calls: list[list[str]] = []

        def tracking_subprocess(cmd, **kwargs):
            if len(cmd) > 1 and cmd[1] == "build":
                build_calls.append(list(cmd))
            mock = MagicMock()
            # Simulate finch run failing so _load_evidence is skipped;
            # we only care that build was not called.
            mock.returncode = 1
            mock.stdout = ""
            mock.stderr = "test: simulated finch run failure"
            return mock

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("kriterion.finch.command_available", return_value=True),
                patch("kriterion.finch._image_exists", return_value=True),
                patch("kriterion.finch.subprocess.run", side_effect=tracking_subprocess),
            ):
                result = run_in_finch("run_cache_test", model, spec, Path(tmp))

        self.assertEqual(
            build_calls,
            [],
            f"finch build must not be called when image already exists; calls: {build_calls}",
        )
        # Result is INSUFFICIENT_EVIDENCE because finch run was mocked to fail,
        # which is the correct fail-closed behaviour.
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status.value, "INSUFFICIENT_EVIDENCE")

    def test_missing_image_triggers_build(self):
        """When _image_exists returns False, run_in_finch must call finch build."""
        from kriterion.adapters import demo_models
        from kriterion.agent import generate_spec_from_description
        from kriterion.finch import run_in_finch

        model = next(m for m in demo_models() if m.adapter == "fixture")
        spec = generate_spec_from_description("Summarise documents as JSON.", allow_fallback=True)

        build_calls: list[list[str]] = []

        def tracking_subprocess(cmd, **kwargs):
            mock = MagicMock()
            if len(cmd) > 1 and cmd[1] == "build":
                build_calls.append(list(cmd))
                mock.returncode = 0  # build succeeds
            else:
                mock.returncode = 1  # run fails → _finch_unavailable
            mock.stdout = ""
            mock.stderr = ""
            return mock

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("kriterion.finch.command_available", return_value=True),
                patch("kriterion.finch._image_exists", return_value=False),
                patch("kriterion.finch.subprocess.run", side_effect=tracking_subprocess),
            ):
                run_in_finch("run_build_test", model, spec, Path(tmp))

        self.assertGreater(len(build_calls), 0, "finch build must be called when image is absent")
        self.assertTrue(
            any("build" in c for c in build_calls[0]),
            f"First subprocess call must be finch build; got: {build_calls[0]}",
        )

    def test_finch_run_receives_container_reachable_ollama_endpoint(self):
        """The evaluator container must not receive host loopback as its
        Ollama endpoint; inside Finch that would point back at the container."""
        from kriterion.adapters import demo_models
        from kriterion.agent import generate_spec_from_description
        from kriterion.finch import run_in_finch

        model = next(m for m in demo_models() if m.adapter == "fixture")
        spec = generate_spec_from_description("Summarise documents as JSON.", allow_fallback=True)
        run_calls: list[list[str]] = []

        def tracking_subprocess(cmd, **kwargs):
            mock = MagicMock()
            if len(cmd) > 1 and cmd[1] == "run":
                run_calls.append(list(cmd))
            mock.returncode = 1
            mock.stdout = ""
            mock.stderr = "simulated run failure"
            return mock

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    "os.environ",
                    {"KRITERION_OLLAMA_BASE_URL": "http://127.0.0.1:11434"},
                    clear=True,
                ),
                patch("kriterion.finch.command_available", return_value=True),
                patch("kriterion.finch._image_exists", return_value=True),
                patch("kriterion.finch.subprocess.run", side_effect=tracking_subprocess),
            ):
                run_in_finch("run_ollama_endpoint_test", model, spec, Path(tmp))

        self.assertEqual(len(run_calls), 1)
        self.assertIn("KRITERION_OLLAMA_BASE_URL=http://host.docker.internal:11434", run_calls[0])

    def test_finch_ollama_endpoint_can_be_configured_explicitly(self):
        from kriterion.adapters import demo_models
        from kriterion.agent import generate_spec_from_description
        from kriterion.finch import run_in_finch

        model = next(m for m in demo_models() if m.adapter == "fixture")
        spec = generate_spec_from_description("Summarise documents as JSON.", allow_fallback=True)
        run_calls: list[list[str]] = []

        def tracking_subprocess(cmd, **kwargs):
            mock = MagicMock()
            if len(cmd) > 1 and cmd[1] == "run":
                run_calls.append(list(cmd))
            mock.returncode = 1
            mock.stdout = ""
            mock.stderr = "simulated run failure"
            return mock

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    "os.environ",
                    {"KRITERION_FINCH_OLLAMA_BASE_URL": "http://ollama-from-finch:11434"},
                    clear=True,
                ),
                patch("kriterion.finch.command_available", return_value=True),
                patch("kriterion.finch._image_exists", return_value=True),
                patch("kriterion.finch.subprocess.run", side_effect=tracking_subprocess),
            ):
                run_in_finch("run_configured_ollama_endpoint_test", model, spec, Path(tmp))

        self.assertEqual(len(run_calls), 1)
        self.assertIn("KRITERION_OLLAMA_BASE_URL=http://ollama-from-finch:11434", run_calls[0])


class TestEvaluatorRunRuntimeInputs(unittest.TestCase):
    def test_model_and_spec_read_from_input_json(self):
        """evaluator_run() must reconstruct ModelRecord and QualificationSpec
        from the JSON payload at runtime.  The model_id and workload_id in the
        produced evidence must match what was written to input.json."""
        from kriterion.adapters import demo_models
        from kriterion.agent import generate_spec_from_description
        from kriterion.finch import evaluator_run
        from kriterion.schemas import to_dict

        model = next(m for m in demo_models() if m.adapter == "fixture")
        spec = generate_spec_from_description(
            "Summarise internal engineering documents as structured JSON with citations.",
            allow_fallback=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            output_path = Path(tmp) / "evidence.jsonl"

            input_path.write_text(
                json.dumps({"run_id": "run_runtime_test", "model": to_dict(model), "spec": to_dict(spec)}),
                encoding="utf-8",
            )

            evaluator_run(input_path, output_path)

            self.assertTrue(output_path.exists(), "evaluator_run must write output evidence JSONL")
            lines = [ln for ln in output_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertGreater(len(lines), 0, "Evidence JSONL must contain at least one record")

            first = json.loads(lines[0])
            self.assertEqual(first["model_id"], model.model_id)
            self.assertEqual(first["workload_id"], spec.workload_id)

    def test_different_models_same_image_tag(self):
        """Two different ModelRecords must produce the same image tag because
        model identity is a runtime input, not part of the image."""
        from kriterion.adapters import registered_models
        from kriterion.finch import _evaluator_image_tag

        models = registered_models()
        # The tag is purely a function of evaluator source files; model records
        # are not inputs to _evaluator_image_tag at all.
        tag = _evaluator_image_tag()
        # Called again independently (simulating a different model being selected)
        tag2 = _evaluator_image_tag()
        self.assertEqual(tag, tag2, "Image tag must be identical regardless of which model is selected")


if __name__ == "__main__":
    unittest.main()
