from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from kriterion.api.handler import handle


class ApiContractTest(unittest.TestCase):
    def test_workload_description_required(self):
        response = handle({"body": json.dumps({"model_id": "hf_tiny_gpt2_local"})}, None)
        self.assertEqual(response["statusCode"], 400)

    def test_ui_api_contract_uses_description(self):
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


if __name__ == "__main__":
    unittest.main()
