from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import patch

from kriterion.adapters import (
    LocalFixtureAdapter,
    OllamaAdapter,
    TransformersLocalAdapter,
    adapter_for_model,
    discover_ollama_models,
    registered_models,
)
from kriterion.schemas import ModelRecord


class _FakeHttpResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class OllamaDiscoveryTest(unittest.TestCase):
    def test_discovery_maps_model_metadata_and_digest(self):
        payload = {
            "models": [
                {
                    "name": "llama3.2:3b",
                    "model": "llama3.2:3b",
                    "digest": "sha256:abc123",
                    "size": 2000000,
                    "details": {
                        "family": "llama",
                        "parameter_size": "3.21B",
                        "quantization_level": "Q4_K_M",
                    },
                }
            ]
        }
        with patch("kriterion.adapters.urllib_request.urlopen", return_value=_FakeHttpResponse(payload)) as urlopen:
            models = discover_ollama_models()

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/tags")
        self.assertEqual(request.method, "GET")
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model.model_id, "ollama:llama3.2:3b")
        self.assertEqual(model.name, "llama3.2:3b")
        self.assertEqual(model.source, "ollama")
        self.assertEqual(model.revision, "sha256:abc123")
        self.assertEqual(model.artifact_hash, "sha256:abc123")
        self.assertEqual(model.architecture, "llama")
        self.assertEqual(model.parameter_count, "3.21B")
        self.assertEqual(model.quantization, "Q4_K_M")
        self.assertIsNone(model.license)
        self.assertEqual(model.adapter, "ollama")

    def test_discovery_handles_multiple_models(self):
        payload = {
            "models": [
                {"name": "llama3.2:3b", "digest": "sha256:first", "details": {}},
                {"name": "qwen2.5:7b", "digest": "sha256:second", "details": {"family": "qwen2"}},
            ]
        }
        with patch("kriterion.adapters.urllib_request.urlopen", return_value=_FakeHttpResponse(payload)):
            models = discover_ollama_models()

        self.assertEqual([model.name for model in models], ["llama3.2:3b", "qwen2.5:7b"])
        self.assertEqual([model.revision for model in models], ["sha256:first", "sha256:second"])
        self.assertEqual(models[1].architecture, "qwen2")

    def test_discovery_skips_records_without_digest_instead_of_fabricating_metadata(self):
        payload = {
            "models": [
                {"name": "missing-digest:latest", "details": {"family": "llama"}},
                {"name": "valid:latest", "digest": "sha256:valid", "details": {}},
            ]
        }
        with patch("kriterion.adapters.urllib_request.urlopen", return_value=_FakeHttpResponse(payload)):
            models = discover_ollama_models()

        self.assertEqual([model.name for model in models], ["valid:latest"])

    def test_discovery_returns_empty_when_ollama_unavailable(self):
        with patch("kriterion.adapters.urllib_request.urlopen", side_effect=ConnectionError("connection refused")):
            models = discover_ollama_models()

        self.assertEqual(models, [])


class OllamaAdapterTest(unittest.TestCase):
    def setUp(self):
        self.model = ModelRecord(
            model_id="ollama:llama3.2:3b",
            name="llama3.2:3b",
            source="ollama",
            revision="sha256:abc123",
            architecture="llama",
            parameter_count="3.21B",
            quantization="Q4_K_M",
            license=None,
            artifact_hash="sha256:abc123",
            adapter="ollama",
        )

    def test_successful_generation_returns_model_output_and_duration(self):
        payload = {"model": "llama3.2:3b", "response": "Hello from Ollama", "done": True}
        with patch("kriterion.adapters.urllib_request.urlopen", return_value=_FakeHttpResponse(payload)) as urlopen:
            output = OllamaAdapter(self.model).generate("Say hello", max_new_tokens=12)

        self.assertEqual(output.text, "Hello from Ollama")
        self.assertGreaterEqual(output.duration_ms, 1)
        self.assertEqual(output.raw["adapter"], "ollama")
        self.assertEqual(output.raw["model"], "llama3.2:3b")
        self.assertEqual(output.raw["response"], payload)

        request = urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(request_body["model"], "llama3.2:3b")
        self.assertEqual(request_body["prompt"], "Say hello")
        self.assertFalse(request_body["stream"])
        self.assertEqual(request_body["options"]["num_predict"], 12)

    def test_generation_uses_configured_ollama_base_url(self):
        payload = {"model": "llama3.2:3b", "response": "Configured endpoint", "done": True}
        with patch.dict("os.environ", {"KRITERION_OLLAMA_BASE_URL": "http://ollama.example:11434"}, clear=True):
            with patch("kriterion.adapters.urllib_request.urlopen", return_value=_FakeHttpResponse(payload)) as urlopen:
                output = OllamaAdapter(self.model).generate("Say hello")

        self.assertEqual(output.text, "Configured endpoint")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://ollama.example:11434/api/generate")

    def test_generation_failure_returns_error_output_without_fallback(self):
        with patch("kriterion.adapters.urllib_request.urlopen", side_effect=ConnectionError("ollama down")):
            output = OllamaAdapter(self.model).generate("Say hello")

        self.assertIn("KRITERION_MODEL_ERROR", output.text)
        self.assertIn("ollama down", output.text)
        self.assertEqual(output.raw["adapter"], "ollama")
        self.assertEqual(output.raw["model"], "llama3.2:3b")
        self.assertNotEqual(output.text, "Fixture response: workload-specific request handled.")
        self.assertGreaterEqual(output.duration_ms, 1)

    def test_adapter_resolution(self):
        adapter = adapter_for_model(self.model)
        self.assertIsInstance(adapter, OllamaAdapter)
        self.assertEqual(adapter.model.model_id, self.model.model_id)


class ExistingAdapterRegressionTest(unittest.TestCase):
    def test_fixture_adapter_still_resolves_and_generates(self):
        fixture = next(model for model in registered_models() if model.adapter == "fixture")
        adapter = adapter_for_model(fixture)
        self.assertIsInstance(adapter, LocalFixtureAdapter)
        output = adapter.generate("return JSON")
        self.assertIn("summary", output.text)

    def test_transformers_adapter_still_resolves_and_generates_with_mocked_transformers(self):
        transformer_model = next(model for model in registered_models() if model.adapter == "transformers_local")
        adapter = adapter_for_model(transformer_model)
        self.assertIsInstance(adapter, TransformersLocalAdapter)

        class FakeTokenizer:
            eos_token_id = 0

            def __call__(self, prompt, return_tensors):
                return {"input_ids": [1, 2, 3]}

            def decode(self, output, skip_special_tokens):
                return "hello generated text"

        class FakeTokenizerFactory:
            @staticmethod
            def from_pretrained(model_name_or_path, local_files_only):
                return FakeTokenizer()

        class FakeModel:
            def generate(self, **kwargs):
                return [[1, 2, 3, 4]]

        class FakeModelFactory:
            @staticmethod
            def from_pretrained(model_name_or_path, local_files_only):
                return FakeModel()

        fake_transformers = types.SimpleNamespace(
            AutoTokenizer=FakeTokenizerFactory,
            AutoModelForCausalLM=FakeModelFactory,
        )
        with patch.dict(sys.modules, {"transformers": fake_transformers}):
            output = adapter.generate("prompt")

        self.assertEqual(output.text, "generated text")
        self.assertEqual(output.raw["adapter"], "transformers_local")
        self.assertGreaterEqual(output.duration_ms, 1)


if __name__ == "__main__":
    unittest.main()
