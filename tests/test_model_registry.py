from __future__ import annotations

import unittest
from unittest.mock import patch

from kriterion.model_registry import (
    LOCAL_STATUS_INSTALLED,
    ModelNotFoundError,
    ModelRegistry,
    ProviderModel,
)
from kriterion.schemas import ModelRecord


class _UnavailableProvider:
    provider_id = "unavailable"
    provider_name = "Unavailable Provider"

    def discover(self):
        raise ConnectionError("not running")


class _StaticProvider:
    provider_id = "static"
    provider_name = "Static Provider"

    def __init__(self, models):
        self._models = models

    def discover(self):
        return self._models


class ModelRegistryTest(unittest.TestCase):
    @staticmethod
    def _ollama_model(name: str = "qwen2.5:7b") -> ModelRecord:
        return ModelRecord(
            model_id=f"ollama:{name}",
            name=name,
            source="ollama",
            revision="sha256:qwen",
            architecture="qwen2",
            parameter_count="7B",
            quantization="Q4_K_M",
            license=None,
            artifact_hash="sha256:qwen",
            adapter="ollama",
        )

    def test_provider_registry_discovers_ollama(self):
        ollama_model = self._ollama_model()
        with patch("kriterion.model_registry.discover_ollama_models", return_value=[ollama_model]):
            discoveries = ModelRegistry().discover()

        ollama = next(discovery for discovery in discoveries if discovery.provider_id == "ollama")
        self.assertIsNone(ollama.error)
        self.assertEqual(len(ollama.models), 1)
        self.assertEqual(ollama.models[0].provider_name, "Ollama")
        self.assertEqual(ollama.models[0].status, LOCAL_STATUS_INSTALLED)

    def test_unavailable_provider_does_not_stop_other_discovery(self):
        model = self._ollama_model("gemma3:4b")
        entry = ProviderModel(
            provider_id="static",
            provider_name="Static Provider",
            status=LOCAL_STATUS_INSTALLED,
            model=model,
        )
        registry = ModelRegistry(providers=[_UnavailableProvider(), _StaticProvider([entry])])

        discoveries = registry.discover()

        self.assertEqual(discoveries[0].provider_id, "unavailable")
        self.assertIn("not running", discoveries[0].error)
        self.assertEqual(discoveries[1].models, [entry])

    def test_ollama_models_become_provider_model_records(self):
        ollama_model = self._ollama_model("qwen-fast:latest")
        with patch("kriterion.model_registry.discover_ollama_models", return_value=[ollama_model]):
            entries = ModelRegistry().list_models()

        ollama_entries = [entry for entry in entries if entry.provider_id == "ollama"]
        self.assertEqual(len(ollama_entries), 1)
        self.assertEqual(ollama_entries[0].model.model_id, "ollama:qwen-fast:latest")
        self.assertEqual(ollama_entries[0].model.adapter, "ollama")
        self.assertEqual(ollama_entries[0].provenance["digest"], "sha256:qwen")

    def test_resolve_unknown_model_id_is_clean_error(self):
        registry = ModelRegistry(providers=[_StaticProvider([])])

        with self.assertRaises(ModelNotFoundError) as raised:
            registry.resolve("missing-model")

        self.assertEqual(raised.exception.model_id, "missing-model")


if __name__ == "__main__":
    unittest.main()