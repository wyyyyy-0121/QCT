import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from formulaguard.api import localize
from formulaguard.localize import LocalizationResult
from formulaguard.v4x import (
    VERSION_ALIASES,
    v4_1_default_parameters,
    v4_2_review,
    v4_3_default_parameters,
)
from formulaguard.v52 import V52Decision


ROOT = Path(__file__).resolve().parents[1]


class VersionLineageTests(unittest.TestCase):
    def test_post_v4_studies_have_canonical_v4x_names(self):
        self.assertEqual(VERSION_ALIASES["v4.1"]["legacy_id"], "v5-pcg-r1")
        self.assertEqual(VERSION_ALIASES["v4.2"]["legacy_id"], "v5.2-b")
        self.assertEqual(VERSION_ALIASES["v4.3"]["legacy_id"], "v6-semantic-r1")
        self.assertEqual(VERSION_ALIASES["v5"]["status"], "development")
        self.assertEqual(VERSION_ALIASES["v5"]["canonical_id"], "v5-core-dev-r2")
        self.assertEqual(v4_1_default_parameters()["model_version"], "v4.1-pcg-r1")
        self.assertEqual(v4_3_default_parameters("b")["model_version"], "v4.3-semantic-b")

    def test_canonical_dispatcher_routes_v41_without_changing_legacy_alias(self):
        expected = [LocalizationResult(("Sheet1", "A1"), 1.0)]
        model = object()
        with patch("formulaguard.api.v4_1_scores", return_value=expected) as canonical:
            self.assertIs(localize(model, "v4.1", candidate_limit=9), expected)
            canonical.assert_called_once_with(model, candidate_limit=9)

    def test_canonical_dispatcher_routes_v43_variant(self):
        expected = [LocalizationResult(("Sheet1", "A1"), 1.0)]
        model = object()
        with patch("formulaguard.api.v4_3_scores", return_value=expected) as canonical:
            self.assertIs(localize(model, "formulaguard_v4_3_b"), expected)
            self.assertEqual(canonical.call_args.kwargs["variant"], "b")

    def test_v42_review_relabels_output_without_changing_core_order(self):
        legacy_result = LocalizationResult(
            ("Sheet1", "A1"), 1.0, evidence={"model_version": "v4-dev-r1"}
        )
        legacy = V52Decision(
            variant="b",
            core_ranking=(legacy_result,),
            rescue=None,
            eligible=(),
            status="no_rescue",
            reason="no_eligible_candidate",
            pattern_elite_limit=3,
        )
        with patch("formulaguard.v4x.v52_scores", return_value=legacy):
            decision = v4_2_review(object(), variant="b")
        self.assertEqual(decision.canonical_version, "v4.2-review-b")
        self.assertEqual(decision.legacy_model_version, "v5.2-b")
        self.assertEqual(decision.core_ranking[0].cell, legacy_result.cell)
        self.assertEqual(decision.core_ranking[0].evidence["model_version"], "v4.2-review-b")
        self.assertEqual(decision.core_ranking[0].evidence["legacy_model_version"], "v4-dev-r1")

    def test_historical_model_sources_remain_byte_identical(self):
        expected = {
            "formulaguard/localize.py": "760fbf8519dce5a4604bcc6ba158e9ca44d9434e7e898c85e9f7bc51c6c99c40",
            "formulaguard/v5.py": "4e7d2b5cb5e850b823dc6e3e8e5901667fdae1ebf510a143fade5971af9b2a64",
            "formulaguard/v52.py": "3454998f904d277d7c9a05ba1c0512afdba7bd216d36369ef14a446d4e7af91d",
            "formulaguard/v6.py": "75296073a37c31c422364361d7fde7d6da0a313b816b5e7d7f5cc71b95d2a3c3",
        }
        for relative, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
