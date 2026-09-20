from __future__ import annotations

import unittest
from unittest.mock import patch

from kriterion.agent import generate_spec_from_description
from kriterion.evaluators import _evidence
from kriterion.policy import derive_policy_attributes, evaluate
from kriterion.schemas import DecisionStatus, ModelRecord, Status


class PolicyAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.spec = generate_spec_from_description(
            "Summarize internal documents as structured JSON with citations.",
            allow_fallback=True,
        )
        self.model = ModelRecord(
            model_id="fixture",
            name="fixture",
            source="test",
            revision="1",
            license="mit",
            artifact_hash="sha256:test",
            adapter="fixture",
        )

    def _passing_evidence(self):
        records = []
        for requirement_id, requirement in self.spec.requirements.items():
            records.append(
                _evidence(
                    "run_test",
                    self.model,
                    self.spec,
                    "TEST",
                    requirement_id,
                    requirement_id,
                    requirement_id,
                    "test",
                    "pass",
                    "pass",
                    Status.PASS,
                    requirement.mandatory,
                    score=1.0,
                    threshold=1.0,
                )
            )
        return records

    def test_missing_mandatory_evidence_blocks(self):
        # Python's responsibility is to derive Cedar context attributes faithfully.
        # With no evidence, the Cedar policy's conditions (mandatory_evidence_complete
        # == true AND no_mandatory_failures == true) cannot be satisfied, so Cedar
        # blocks. Verify the attributes Python produces for Cedar are correct.
        attributes, failed_conditions, reason_codes = derive_policy_attributes(self.spec, [])
        self.assertFalse(attributes["mandatory_evidence_complete"])
        self.assertFalse(attributes["no_mandatory_failures"])
        self.assertIn("MANDATORY_EVIDENCE_MISSING", reason_codes)
        self.assertTrue(any("missing mandatory evidence" in c for c in failed_conditions))

    def test_mandatory_error_blocks(self):
        # An ERROR on a mandatory evidence record must be reflected in the Cedar
        # context as no_mandatory_failures=False so Cedar's policy blocks.
        # Python must not suppress or reclassify mandatory errors.
        evidence = self._passing_evidence()
        evidence[0].status = Status.ERROR
        attributes, failed_conditions, reason_codes = derive_policy_attributes(self.spec, evidence)
        self.assertFalse(attributes["no_mandatory_failures"])
        self.assertTrue(any("ERROR" in c for c in failed_conditions))

    def test_cedar_is_authority_for_admit(self):
        with patch("kriterion.policy._cedar_authorize", return_value=(DecisionStatus.ADMIT, None)):
            with patch("kriterion.policy.cedar_decision_consistency", return_value=(["ADMIT", "ADMIT"], 1.0)):
                decision = evaluate(self.spec, self._passing_evidence())
        self.assertEqual(decision.decision, DecisionStatus.ADMIT)


if __name__ == "__main__":
    unittest.main()