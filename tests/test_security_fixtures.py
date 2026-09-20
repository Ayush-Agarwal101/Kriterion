from __future__ import annotations

import unittest
from pathlib import Path

from kriterion.util import read_json, stable_hash


class SecurityFixtureTest(unittest.TestCase):
    def test_fixture_contains_labelled_inputs(self):
        fixture = read_json(Path("fixtures/security-fixtures-v1.json"))
        self.assertEqual(fixture["dataset_id"], "security-fixtures-v1")
        self.assertTrue(fixture["version"])
        self.assertTrue(fixture["cases"])
        for case in fixture["cases"]:
            self.assertIn(case["expected_label"], {"safe", "unsafe"})
            self.assertTrue(case["case_id"])
            self.assertTrue(case["category"])
            self.assertTrue(case["expected_behavior"])
            self.assertTrue(case["input"])
        self.assertTrue(stable_hash(fixture).startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
