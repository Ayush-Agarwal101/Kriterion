from __future__ import annotations

import unittest

from kriterion.agent import example_workload_prompts, generate_spec_from_description


class StrandsFlowTest(unittest.TestCase):
    def test_fallback_is_explicitly_marked(self):
        spec = generate_spec_from_description(
            "I need a coding agent that can run tests but cannot access the public internet.",
            allow_fallback=True,
        )
        self.assertIn(spec.model_requirements["workload_analysis_mode"], {"REAL", "FALLBACK"})
        if spec.model_requirements["workload_analysis_mode"] == "FALLBACK":
            self.assertIn("heuristic_fallback", spec.model_requirements["workload_analysis_source"])


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