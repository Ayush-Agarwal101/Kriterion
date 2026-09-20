from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import patch

from kriterion.agent import example_workload_prompts, generate_spec_from_description
from kriterion.schemas import ModelRecord


class StrandsFlowTest(unittest.TestCase):
    def test_fallback_is_explicitly_marked(self):
        spec = generate_spec_from_description(
            "I need a coding agent that can run tests but cannot access the public internet.",
            allow_fallback=True,
        )
        self.assertIn(spec.model_requirements["workload_analysis_mode"], {"REAL", "FALLBACK"})
        if spec.model_requirements["workload_analysis_mode"] == "FALLBACK":
            self.assertIn("heuristic_fallback", spec.model_requirements["workload_analysis_source"])

    def test_strands_uses_configured_ollama_model_without_cloud_credentials(self):
        captured = {}

        class FakeOllamaModel:
            def __init__(self, **kwargs):
                captured["model_kwargs"] = kwargs

        class FakeAgent:
            def __init__(self, model):
                captured["agent_model"] = model

            def __call__(self, prompt):
                captured["prompt"] = prompt
                return json.dumps(
                    {
                        "required_capabilities": ["summarization"],
                        "security_risks": [],
                        "allowed_tools": [],
                        "forbidden_actions": ["public_internet"],
                        "runtime_limits": {"maximum_p95_latency_ms": 3000},
                        "sandbox_requirements": {"provider": None},
                        "required_tests": ["E01", "E02", "E03", "E04"],
                        "thresholds": {"structured_output": 0.98},
                    }
                )

        fake_strands = types.SimpleNamespace(Agent=FakeAgent)
        fake_ollama_module = types.SimpleNamespace(OllamaModel=FakeOllamaModel)
        with (
            patch.dict(
                sys.modules,
                {
                    "strands": fake_strands,
                    "strands.models": types.SimpleNamespace(),
                    "strands.models.ollama": fake_ollama_module,
                },
            ),
            patch.dict(
                "os.environ",
                {
                    "KRITERION_STRANDS_OLLAMA_MODEL": "qwen-fast:latest",
                    "KRITERION_OLLAMA_BASE_URL": "http://ollama.local:11434",
                },
                clear=False,
            ),
            patch("kriterion.agent.discover_ollama_models") as discover,
        ):
            spec = generate_spec_from_description("Summarize internal documents.")

        discover.assert_not_called()
        self.assertEqual(captured["model_kwargs"]["host"], "http://ollama.local:11434")
        self.assertEqual(captured["model_kwargs"]["model_id"], "qwen-fast:latest")
        self.assertEqual(spec.model_requirements["workload_analysis_mode"], "REAL")
        self.assertEqual(spec.model_requirements["workload_analysis_source"], "strands:ollama:qwen-fast:latest")

    def test_strands_defaults_to_discovered_ollama_model(self):
        captured = {}

        class FakeOllamaModel:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        class FakeAgent:
            def __init__(self, model):
                self.model = model

            def __call__(self, prompt):
                return json.dumps(
                    {
                        "required_capabilities": ["structured_output"],
                        "security_risks": [],
                        "allowed_tools": [],
                        "forbidden_actions": [],
                        "runtime_limits": {},
                        "sandbox_requirements": {},
                        "required_tests": ["E01", "E02", "E03", "E04"],
                        "thresholds": {},
                    }
                )

        discovered = [
            ModelRecord(
                model_id="ollama:qwen2.5:7b",
                name="qwen2.5:7b",
                source="ollama",
                revision="sha256:qwen",
                architecture="qwen2",
                parameter_count="7B",
                quantization=None,
                license=None,
                artifact_hash="sha256:qwen",
                adapter="ollama",
            )
        ]
        with (
            patch.dict(
                sys.modules,
                {
                    "strands": types.SimpleNamespace(Agent=FakeAgent),
                    "strands.models": types.SimpleNamespace(),
                    "strands.models.ollama": types.SimpleNamespace(OllamaModel=FakeOllamaModel),
                },
            ),
            patch.dict("os.environ", {}, clear=True),
            patch("kriterion.agent.discover_ollama_models", return_value=discovered),
        ):
            spec = generate_spec_from_description("Return JSON summaries.")

        self.assertEqual(captured["model_id"], "qwen2.5:7b")
        self.assertEqual(spec.model_requirements["workload_analysis_source"], "strands:ollama:qwen2.5:7b")

    def test_strands_accepts_dict_response_without_text_extraction(self):
        class FakeOllamaModel:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeAgent:
            def __init__(self, model):
                self.model = model

            def __call__(self, prompt):
                return {
                    "required_capabilities": ["summarization", "structured_output"],
                    "security_risks": ["prompt_injection"],
                    "allowed_tools": [],
                    "forbidden_actions": ["public_internet"],
                    "runtime_limits": {"maximum_p95_latency_ms": 3000},
                    "sandbox_requirements": {"provider": None},
                    "logging-and-monitoring": "Continuous",
                    "required_tests": ["E01", "E02", "E03", "E04", "E05"],
                    "thresholds": {"structured_output": 0.98, "document_task": 0.8},
                }

        with (
            patch.dict(
                sys.modules,
                {
                    "strands": types.SimpleNamespace(Agent=FakeAgent),
                    "strands.models": types.SimpleNamespace(),
                    "strands.models.ollama": types.SimpleNamespace(OllamaModel=FakeOllamaModel),
                },
            ),
            patch.dict("os.environ", {"KRITERION_STRANDS_OLLAMA_MODEL": "qwen-fast:latest"}, clear=True),
        ):
            spec = generate_spec_from_description("Summarize documents with citations.")

        self.assertEqual(spec.model_requirements["workload_analysis_mode"], "REAL")
        self.assertIn("summarization", spec.required_capabilities)
        self.assertIn("E05", spec.required_tests)

    def test_strands_accepts_object_with_dict_message(self):
        class FakeResult:
            message = {
                "required_capabilities": ["structured_output"],
                "security_risks": [],
                "allowed_tools": [],
                "forbidden_actions": [],
                "runtime_limits": {},
                "sandbox_requirements": {},
                "required_tests": ["E01", "E02", "E03", "E04"],
                "thresholds": {},
            }

        class FakeOllamaModel:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeAgent:
            def __init__(self, model):
                self.model = model

            def __call__(self, prompt):
                return FakeResult()

        with (
            patch.dict(
                sys.modules,
                {
                    "strands": types.SimpleNamespace(Agent=FakeAgent),
                    "strands.models": types.SimpleNamespace(),
                    "strands.models.ollama": types.SimpleNamespace(OllamaModel=FakeOllamaModel),
                },
            ),
            patch.dict("os.environ", {"KRITERION_STRANDS_OLLAMA_MODEL": "qwen-fast:latest"}, clear=True),
        ):
            spec = generate_spec_from_description("Return structured JSON.")

        self.assertEqual(spec.model_requirements["workload_analysis_mode"], "REAL")
        self.assertIn("structured_output", spec.required_capabilities)


class HeuristicContextTest(unittest.TestCase):
    """B2 regression — tokens that appear in prohibition context must not
    trigger the coding / Firecracker-sandbox branch of the heuristic analyser.

    The document-workload example description contains both "execute" and "code"
    inside the clause "must not execute code".  Prior to the fix, both tokens
    caused the heuristic to add mandatory coding (E06) and sandbox (E10)
    requirements to a workload that should never require them.
    """

    def test_document_workload_prohibition_does_not_require_sandbox(self):
        # "must not execute code" must NOT trigger the coding/sandbox branch.
        spec = generate_spec_from_description(
            example_workload_prompts()["Internal document agent"],
            allow_fallback=True,
        )
        self.assertNotIn(
            "E06", spec.required_tests,
            "document workload must not require the coding evaluator (E06)",
        )
        self.assertNotIn(
            "E10", spec.required_tests,
            "document workload must not require the sandbox evaluator (E10)",
        )
        self.assertNotIn(
            "coding", spec.requirements,
            "document workload must not have a coding requirement",
        )
        self.assertNotIn(
            "sandbox", spec.requirements,
            "document workload must not have a sandbox requirement",
        )

    def test_document_workload_prohibition_does_not_set_sandbox_provider(self):
        # sandbox_requirements.provider must remain None for the document workload.
        spec = generate_spec_from_description(
            example_workload_prompts()["Internal document agent"],
            allow_fallback=True,
        )
        provider = spec.sandbox_requirements.get("provider")
        self.assertIsNone(
            provider,
            f"document workload sandbox provider must be None, got {provider!r}",
        )

    def test_coding_workload_still_requires_sandbox(self):
        # The coding-agent description ("repository", "patch", "run tests") must
        # continue to trigger the coding/sandbox branch after removing the
        # false-positive tokens.
        spec = generate_spec_from_description(
            example_workload_prompts()["Autonomous coding agent"],
            allow_fallback=True,
        )
        self.assertIn(
            "E06", spec.required_tests,
            "coding workload must require the coding evaluator (E06)",
        )
        self.assertIn(
            "E10", spec.required_tests,
            "coding workload must require the sandbox evaluator (E10)",
        )
        self.assertIn(
            "coding", spec.requirements,
            "coding workload must have a coding requirement",
        )
        self.assertIn(
            "sandbox", spec.requirements,
            "coding workload must have a sandbox requirement",
        )

    def test_bare_execute_word_alone_does_not_trigger_coding_branch(self):
        # A description containing only "execute" (in prohibition) must not add
        # coding or sandbox requirements.
        spec = generate_spec_from_description(
            "An agent that must not execute arbitrary commands or scripts.",
            allow_fallback=True,
        )
        self.assertNotIn("E06", spec.required_tests)
        self.assertNotIn("coding", spec.requirements)

    def test_bare_code_word_alone_does_not_trigger_coding_branch(self):
        # A description containing only "code" (in prohibition) must not add
        # coding or sandbox requirements.
        spec = generate_spec_from_description(
            "An agent that must not run any code outside the document summarisation task.",
            allow_fallback=True,
        )
        self.assertNotIn("E06", spec.required_tests)
        self.assertNotIn("coding", spec.requirements)


if __name__ == "__main__":
    unittest.main()
