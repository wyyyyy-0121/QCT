import json
import unittest

from scripts.validate_v5_model_discovery_gate1 import (
    CARDS_MD_PATH,
    CARDS_PATH,
    RESULT_MD_PATH,
    RESULT_PATH,
    build_gate_result,
    load_cards,
    render_cards,
    render_result,
    validate_cards,
)


class ModelDiscoveryGate1Tests(unittest.TestCase):
    def test_all_required_method_cards_are_present_and_valid(self):
        cards = load_cards()
        self.assertEqual(validate_cards(cards), [])
        self.assertEqual(len(cards["methods"]), 9)

    def test_excelint_card_records_official_current_cli_only(self):
        cards = load_cards()
        excelint = next(item for item in cards["methods"] if item["id"] == "excelint")
        self.assertEqual(excelint["implementation_identity"], "official_current_implementation")
        self.assertEqual(excelint["implementation_status"], "linux_cli_verified")
        self.assertTrue(excelint["runtime_record"]["deterministic_repeat_verified"])
        self.assertIn("not a complete per-formula ranking", excelint["runtime_record"]["output_contract"])

    def test_rendered_gate1_artifacts_are_reproducible(self):
        cards = load_cards()
        result = build_gate_result(cards)
        self.assertEqual(CARDS_MD_PATH.read_text(encoding="utf-8"), render_cards(cards))
        self.assertEqual(RESULT_MD_PATH.read_text(encoding="utf-8"), render_result(result))
        self.assertEqual(json.loads(RESULT_PATH.read_text(encoding="utf-8")), result)


if __name__ == "__main__":
    unittest.main()
