from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kriterion.adapters import demo_models
from kriterion.agent import example_workload_prompts
from kriterion.metrics import aggregate_runs, security_metrics
from kriterion.orchestrator import qualify


class AcceptanceTest(unittest.TestCase):
    def test_same_model_different_workload_decisions(self):
        root = Path(tempfile.mkdtemp())
        try:
            model = next(m for m in demo_models() if m.adapter == "fixture")
            examples = example_workload_prompts()
            coding = qualify(model, examples["Autonomous coding agent"], root, allow_local_evaluator=True, allow_strands_fallback=True)
            docs = qualify(model, examples["Internal document agent"], root, allow_local_evaluator=True, allow_strands_fallback=True)
            self.assertEqual(coding.decision["status"], "BLOCK")
            summary = aggregate_runs(root / "runs", root / "metrics" / "summary.json")
            self.assertEqual(summary["sample_sizes"]["qualification_runs"], 2)
            self.assertEqual(summary["sample_sizes"]["workloads"], 2)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class DocumentTaskFixtureAdapterTest(unittest.TestCase):
    """B3 regression — LocalFixtureAdapter must produce a document-task response
    that the _capability_tasks (E05) evaluator accepts.

    The evaluator accepts any non-empty response containing at least one of the
    strings "evidence", "task", or "source".  Prior to the fix the fixture adapter
    returned a generic string that contained none of these keywords, causing every
    E05 record to FAIL regardless of workload.
    """

    def setUp(self):
        self._root = Path(tempfile.mkdtemp())
        self._model = next(m for m in demo_models() if m.adapter == "fixture")

    def tearDown(self):
        shutil.rmtree(self._root, ignore_errors=True)

    def _run_document_workload(self):
        return qualify(
            self._model,
            example_workload_prompts()["Internal document agent"],
            self._root,
            allow_local_evaluator=True,
            allow_strands_fallback=True,
        )

    def _load_evidence(self, run):
        evidence_path = self._root / "evidence" / f"{run.qualification_run_id}.jsonl"
        return [
            json.loads(line)
            for line in evidence_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_document_workload_produces_e05_evidence(self):
        run = self._run_document_workload()
        records = self._load_evidence(run)
        e05 = [r for r in records if r["test_id"] == "E05"]
        self.assertGreater(len(e05), 0, "document workload must produce at least one E05 evidence record")

    def test_e05_document_task_passes_with_fixture_adapter(self):
        # Every DOC-001 / DOC-002 / DOC-003 case must PASS — the fixture adapter
        # response must contain at least one of "evidence", "task", or "source".
        run = self._run_document_workload()
        records = self._load_evidence(run)
        e05 = [r for r in records if r["test_id"] == "E05"]
        self.assertGreater(len(e05), 0)
        failing = [r for r in e05 if r["status"] != "PASS"]
        self.assertEqual(
            failing, [],
            f"All E05 (document_task) records must PASS with the fixture adapter; "
            f"failing cases: {[r['test_case_id'] for r in failing]}",
        )

    def test_document_workload_does_not_produce_e06_or_e10_evidence(self):
        # After B2 fix, the document workload must not require the coding (E06)
        # or sandbox (E10) evaluators.  No such evidence records should appear.
        run = self._run_document_workload()
        records = self._load_evidence(run)
        e06 = [r for r in records if r["test_id"] == "E06"]
        e10 = [r for r in records if r["test_id"] == "E10"]
        self.assertEqual(e06, [], "document workload must not produce E06 (coding) evidence")
        self.assertEqual(e10, [], "document workload must not produce E10 (sandbox) evidence")

    def test_security_metrics_tp_positive_after_fixture_run(self):
        # After B1 fix, a fixture-model run where all security cases PASS must
        # produce TP > 0 (not TP=0 as with the old inverted calculation).
        # We read evidence from the run and call security_metrics directly so this
        # test does not depend on Cedar or Finch being installed.
        from kriterion.schemas import EvidenceRecord, SandboxRecord, Status

        run = self._run_document_workload()
        raw = self._load_evidence(run)

        # Reconstruct lightweight EvidenceRecord objects from stored JSONL.
        evidence = []
        for r in raw:
            if r.get("expected_label") in {"safe", "unsafe"}:
                evidence.append(
                    EvidenceRecord(
                        evidence_id=r["evidence_id"],
                        qualification_run_id=r["qualification_run_id"],
                        model_id=r["model_id"],
                        model_revision=r["model_revision"],
                        workload_id=r["workload_id"],
                        spec_id=r["spec_id"],
                        test_id=r["test_id"],
                        test_name=r["test_name"],
                        test_version=r["test_version"],
                        test_case_id=r["test_case_id"],
                        requirement_id=r["requirement_id"],
                        category=r["category"],
                        expected_behavior=r["expected_behavior"],
                        observed_behavior=r["observed_behavior"],
                        status=Status(r["status"]),
                        score=r.get("score"),
                        threshold=r.get("threshold"),
                        mandatory=r["mandatory"],
                        timestamp_utc=r["timestamp_utc"],
                        duration_ms=r["duration_ms"],
                        expected_label=r.get("expected_label"),
                        predicted_label=r.get("predicted_label"),
                    )
                )

        if not evidence:
            self.skipTest("No labelled security evidence produced by this run")

        result = security_metrics(evidence)
        # The fixture adapter correctly refuses every adversarial prompt → all
        # unsafe cases should PASS → TP == number of unsafe cases, FN == 0.
        unsafe_pass = sum(
            1 for r in raw
            if r.get("expected_label") == "unsafe" and r.get("status") == "PASS"
        )
        self.assertEqual(
            result["true_positive"], unsafe_pass,
            "TP must equal the count of correctly-refused adversarial cases",
        )
        self.assertEqual(result["false_negative"], 0,
                         "FN must be 0 when the fixture adapter refuses every adversarial prompt")
        if unsafe_pass > 0:
            self.assertIsNotNone(result["recall"])
            self.assertGreater(result["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()