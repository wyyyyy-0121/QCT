import tempfile
import unittest
from pathlib import Path

from formulaguard.workbook import WorkbookModel
from scripts.score_model_discovery_min_info import (
    choose_visible_output,
    graph_distance_rank,
)
from scripts.score_model_discovery_min_info import (
    metric as min_info_metric,
)
from scripts.score_model_discovery_min_info import (
    write_immutable as write_branch_c_immutable,
)
from scripts.score_model_discovery_signals import (
    _fixed_macro,
    _metric,
)
from scripts.score_model_discovery_signals import (
    parse_cells as signal_parse_cells,
)
from scripts.score_model_discovery_signals import (
    write_immutable as write_signal_immutable,
)


class ModelDiscoveryGate2Tests(unittest.TestCase):
    def test_signal_metric_and_cell_parser_are_deterministic(self):
        self.assertEqual(signal_parse_cells("S!A1;S!A1|S!B2"), ["S!A1", "S!B2"])
        self.assertEqual(_metric(["S!A1", "S!B2"], ["S!B2"])["rank"], 2)
        self.assertEqual(_metric(["S!A1"], ["S!C3"])["source_found"], 0)

    def test_fixed_macro_uses_structure_groups(self):
        rows = [
            {
                "case_kind": "error",
                "structure_group": "g1",
                "selector_metrics": {"top1": 1, "top5": 1, "mrr": 1.0, "region_hit": 1, "source_block_coverage": 1},
            },
            {
                "case_kind": "error",
                "structure_group": "g1",
                "selector_metrics": {"top1": 0, "top5": 0, "mrr": 0.2, "region_hit": 0, "source_block_coverage": 0},
            },
            {
                "case_kind": "error",
                "structure_group": "g2",
                "selector_metrics": {"top1": 0, "top5": 0, "mrr": 0.1, "region_hit": 0, "source_block_coverage": 0},
            },
        ]
        # g1 contributes its event mean (0.5), g2 contributes 0; macro = .25.
        self.assertAlmostEqual(_fixed_macro(rows)["top5"], 0.25)

    def test_key_output_proxy_and_cone_ranking(self):
        model = WorkbookModel.from_cells(
            {("Sheet", "A1"): 1, ("Sheet", "B1"): 2},
            {
                ("Sheet", "C1"): "=A1+B1",
                ("Sheet", "D1"): "=C1*2",
            },
        )
        output, metadata = choose_visible_output(model)
        self.assertEqual(output, ("Sheet", "D1"))
        self.assertEqual(metadata["selection_rule"], "visible_formula_sink_with_largest_ancestor_cone")
        ranking, info = graph_distance_rank(model, output, {"Sheet!C1": 1, "Sheet!D1": 2})
        self.assertEqual(ranking, ["Sheet!C1", "Sheet!D1"])
        self.assertEqual(info["cone_formula_count"], 2)

    def test_min_info_metric_distinguishes_action_and_hit(self):
        hit = min_info_metric(["Sheet!C1", "Sheet!D1"], ["Sheet!D1"])
        miss = min_info_metric(["Sheet!C1"], ["Sheet!D1"])
        self.assertEqual(hit, {"acted": 1, "hit": 1, "action_count": 2, "rank": 2})
        self.assertEqual(miss["acted"], 1)
        self.assertEqual(miss["hit"], 0)

    def test_completed_event_outputs_are_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event_scores.jsonl"
            payload = b"{\"event_id\":\"e1\"}\n"
            write_signal_immutable(path, payload, description="Gate 2 event scores")
            write_branch_c_immutable(path, payload, description="Branch C event scores")
            with self.assertRaises(ValueError):
                write_signal_immutable(path, b"tampered\n", description="Gate 2 event scores")


if __name__ == "__main__":
    unittest.main()
