from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from kriterion.api.handler import handle
from kriterion.adapters import registered_models
from kriterion.schemas import ModelRecord


class ApiContractTest(unittest.TestCase):
    def test_workload_description_required(self):
        response = handle({"body": json.dumps({"model_id": "hf_tiny_gpt2_local"})}, None)
        self.assertEqual(response["statusCode"], 400)

    def test_ui_api_contract_uses_description(self):
        with patch("kriterion.model_registry.discover_ollama_models", return_value=[]):
            with patch("kriterion.api.handler.qualify") as qualify:
                qualify.return_value.qualification_run_id = "run_test"
                qualify.return_value.decision = {"status": "BLOCK"}
                response = handle(
                    {
                        "body": json.dumps(
                            {
                                "model_id": "hf_tiny_gpt2_local",
                                "workload_description": "Summarize documents.",
                                "allow_strands_fallback": True,
                            }
                        )
                    },
                    None,
                )
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(qualify.called)

    def test_api_resolves_ollama_model(self):
        model = ModelRecord(
            model_id="ollama:qwen2.5:7b",
            name="qwen2.5:7b",
            source="ollama",
            revision="sha256:qwen",
            architecture="qwen2",
            parameter_count="7B",
            quantization="Q4_K_M",
            license=None,
            artifact_hash="sha256:qwen",
            adapter="ollama",
        )
        with patch("kriterion.model_registry.discover_ollama_models", return_value=[model]):
            with patch("kriterion.api.handler.qualify") as qualify:
                qualify.return_value.qualification_run_id = "run_ollama"
                qualify.return_value.decision = {"status": "ADMIT"}
                response = handle(
                    {
                        "body": json.dumps(
                            {
                                "model_id": "ollama:qwen2.5:7b",
                                "workload_description": "Summarize engineering docs.",
                            }
                        )
                    },
                    None,
                )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(qualify.call_args.args[0].model_id, "ollama:qwen2.5:7b")

    def test_api_still_resolves_fixture_and_transformers_models(self):
        with patch("kriterion.model_registry.discover_ollama_models", return_value=[]):
            with patch("kriterion.api.handler.qualify") as qualify:
                qualify.return_value.qualification_run_id = "run_fixture"
                qualify.return_value.decision = {"status": "BLOCK"}
                for model in registered_models():
                    response = handle(
                        {
                            "body": json.dumps(
                                {
                                    "model_id": model.model_id,
                                    "workload_description": "Summarize engineering docs.",
                                }
                            )
                        },
                        None,
                    )
                    self.assertEqual(response["statusCode"], 200)

        resolved_ids = [call.args[0].model_id for call in qualify.call_args_list]
        self.assertIn("hf_tiny_gpt2_local", resolved_ids)
        self.assertIn("model_demo_fixture_001", resolved_ids)

    def test_unknown_model_id_returns_clean_error(self):
        with patch("kriterion.model_registry.discover_ollama_models", return_value=[]):
            response = handle(
                {
                    "body": json.dumps(
                        {
                            "model_id": "does-not-exist",
                            "workload_description": "Summarize engineering docs.",
                        }
                    )
                },
                None,
            )

        self.assertEqual(response["statusCode"], 404)
        payload = json.loads(response["body"])
        self.assertEqual(payload["model_id"], "does-not-exist")
        self.assertIn("unknown model_id", payload["error"])


if __name__ == "__main__":
    unittest.main()
