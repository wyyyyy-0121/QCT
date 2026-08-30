import json
import unittest
from pathlib import Path

from scripts.validate_v5_model_discovery_phase0 import (
    CONTRACT_PATH,
    DECISION_LOG_PATH,
    GATE_RESULT_PATH,
    LEDGER_PATH,
    PHASE0_AUDIT_PATH,
    POWER_JSON_PATH,
    STATUS_PATH,
    build_power_report,
    exact_paired_sign_power,
    validate_documents,
    validate_ledger,
    validate_power_report,
)


ROOT = Path(__file__).resolve().parents[1]


class ModelDiscoveryPhase0Tests(unittest.TestCase):
    def test_power_is_deterministic_and_conservative_for_five_points(self):
        first = build_power_report()
        second = build_power_report()
        self.assertEqual(first, second)
        summary = first["summary_for_five_percentage_points"]
        self.assertLess(summary["25"]["five_pp_max_power"], 0.80)
        self.assertLess(summary["30"]["five_pp_max_power"], 0.80)

    def test_power_rejects_invalid_discordance_assumptions(self):
        with self.assertRaises(ValueError):
            exact_paired_sign_power(30, 0.25, 0.20)

    def test_tracked_ledger_matches_phase0_audit(self):
        ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        phase0 = json.loads(PHASE0_AUDIT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate_ledger(ledger, phase0), [])

    def test_power_json_matches_reproducible_calculation(self):
        report = json.loads(POWER_JSON_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate_power_report(report), [])

    def test_phase0_documents_exist_and_have_no_active_legacy_line(self):
        for path in (
            STATUS_PATH,
            CONTRACT_PATH,
            DECISION_LOG_PATH,
            GATE_RESULT_PATH,
            LEDGER_PATH,
            POWER_JSON_PATH,
        ):
            self.assertTrue(path.is_file(), path)
        self.assertEqual(validate_documents(), [])


if __name__ == "__main__":
    unittest.main()
