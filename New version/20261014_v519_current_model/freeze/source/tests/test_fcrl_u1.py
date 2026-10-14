import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import torch
from torch import nn

from formulaguard.fcrl import build_table_input
from formulaguard.fcrl_torch import (
    FCRLModel,
    FCRLTensorBatch,
    generate_prefix_beam,
    load_tokenizer_runtime,
    tensorize_tables,
)
from formulaguard.fcrl_u1 import prediction_metrics, score_u1_predictions
from formulaguard.workbook import WorkbookModel

ROOT = Path(__file__).resolve().parents[1]
FORTAP_SOURCE = ROOT / "data/external/model_discovery/raw/TUTA_table_understanding"


def tensor_batch(*, range_label: torch.Tensor | None = None) -> FCRLTensorBatch:
    batch_size, sequence_length, sketch_length = 1, 4, 3
    return FCRLTensorBatch(
        token_id=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        num_mag=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        num_pre=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        num_top=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        num_low=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        token_order=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        pos_row=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        pos_col=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        pos_top=torch.zeros((batch_size, sequence_length, 4), dtype=torch.long),
        pos_left=torch.zeros((batch_size, sequence_length, 4), dtype=torch.long),
        format_vec=torch.zeros((batch_size, sequence_length, 11)),
        indicator=torch.zeros((batch_size, sequence_length), dtype=torch.long),
        formula_label=torch.tensor([[1, 1, 0, 0]], dtype=torch.long),
        src_sketch=torch.zeros((batch_size, sketch_length), dtype=torch.long),
        tgt_sketch=torch.tensor([[1, 1, 41]], dtype=torch.long),
        candi_cell_token_mask=torch.tensor([[0, 0, 1, 0]], dtype=torch.long),
        range_label=(
            range_label
            if range_label is not None
            else torch.zeros((batch_size, sketch_length), dtype=torch.long)
        ),
        range_maps=({2: "B2"},),
        encoder_hashes=("synthetic",),
        reachable_references=(0,),
        total_references=(1,),
    )


class _StaticBackbone(nn.Module):
    def forward(self, *, token_id, **_unused):
        return torch.zeros((*token_id.shape, 4), device=token_id.device)


class _LossDecoder(nn.Module):
    padding_idx = 41

    def __init__(self):
        super().__init__()
        self.scale = nn.Parameter(torch.tensor(0.25))

    def sketch_logits(self, source, encoded_states, formula_cell_states, last_token=False):
        length = 1 if last_token else source.size(1)
        logits = self.scale * torch.ones(
            (source.size(0), length, 42), device=source.device
        )
        hidden = self.scale * torch.ones(
            (source.size(0), length, 8), device=source.device
        )
        return logits, hidden

    def range_logits(
        self, sketch_hidden, encoded_states, candi_cell_token_mask, formula_cell_states
    ):
        logits = self.scale * torch.ones(
            (sketch_hidden.size(0), sketch_hidden.size(1), encoded_states.size(1)),
            device=sketch_hidden.device,
        )
        return logits, logits


class _BeamTokenizer:
    _tokens: ClassVar[dict[str, int]] = {"<START>": 0, "<END>": 1, "<RANGE>": 3}

    def fp_tok2id(self, token):
        return self._tokens[token]


class _BeamDecoder:
    def sketch_logits(self, source, encoded_states, formula_cell_states, last_token=False):
        length = 1 if last_token else source.size(1)
        logits = torch.full((source.size(0), length, 42), -1000.0)
        if last_token:
            next_token = {1: 20, 2: 3}.get(source.size(1), 1)
            logits[:, -1, next_token] = 0.0
        hidden = torch.zeros((source.size(0), length, 8))
        return logits, hidden

    def range_logits(
        self, sketch_hidden, encoded_states, candi_cell_token_mask, formula_cell_states
    ):
        logits = torch.full(
            (sketch_hidden.size(0), sketch_hidden.size(1), encoded_states.size(1)),
            -1000.0,
        )
        logits[:, :, 2] = 0.0
        return logits, logits


class _BeamModel:
    hidden_size = 4

    def __init__(self):
        self.decoder = _BeamDecoder()

    def eval(self):
        return self

    def encode(self, batch):
        return torch.zeros((*batch.token_id.shape, self.hidden_size))


class FCRLU1TensorTests(unittest.TestCase):
    @unittest.skipUnless(FORTAP_SOURCE.is_dir(), "frozen ForTaP source unavailable")
    def test_range_map_contains_all_visible_candidates_not_only_gold_references(self):
        cells = {
            ("Sheet", "A1"): "Item",
            ("Sheet", "B1"): "Value",
            ("Sheet", "A2"): "First",
            ("Sheet", "B2"): 11,
            ("Sheet", "A3"): "Second",
            ("Sheet", "B3"): 13,
            ("Sheet", "A4"): "Total",
            ("Sheet", "B4"): 24,
        }
        model = WorkbookModel.from_cells(cells, {("Sheet", "B4"): "=SUM(B2:B3)"})
        runtime = load_tokenizer_runtime(FORTAP_SOURCE)
        batch = tensorize_tables(
            [build_table_input(model, ("Sheet", "B4"))],
            runtime,
        )
        self.assertEqual(
            set(batch.range_maps[0].values()),
            {"A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4"},
        )

    def test_decoder_loss_accepts_a_batch_without_reachable_ranges(self):
        model = FCRLModel(_StaticBackbone(), _LossDecoder(), hidden_size=4)
        loss, sketch_loss, range_loss = model.decoder_loss(tensor_batch())
        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(torch.isfinite(sketch_loss))
        self.assertEqual(float(range_loss.detach()), 0.0)
        loss.backward()
        self.assertIsNotNone(model.decoder.scale.grad)

    def test_beam_prediction_is_deterministic_and_resolves_visible_pointer(self):
        runtime = SimpleNamespace(
            args=SimpleNamespace(beam_size=1, beam_alpha=1.0, max_length=8),
            tokenizer=_BeamTokenizer(),
            official=SimpleNamespace(
                generation=SimpleNamespace(
                    REV_FP_VOCAB={0: "<START>", 1: "<END>", 3: "<RANGE>", 20: "SUM"}
                )
            ),
            model=_BeamModel(),
        )
        batch = tensor_batch()
        first = generate_prefix_beam(runtime, batch)
        second = generate_prefix_beam(runtime, batch)
        self.assertEqual(first, second)
        self.assertEqual(first[0].key, "SUM B2")


class FCRLU1MetricTests(unittest.TestCase):
    def test_structure_group_macro_weights_groups_equally(self):
        rows = [
            {
                "structure_group": "large",
                "workbook_id": "wb-1",
                "model_top1": False,
                "model_top5": False,
                "global_top5": False,
                "local_peer_top5": False,
            },
            {
                "structure_group": "large",
                "workbook_id": "wb-1",
                "model_top1": False,
                "model_top5": False,
                "global_top5": False,
                "local_peer_top5": False,
            },
            {
                "structure_group": "small",
                "workbook_id": "wb-2",
                "model_top1": True,
                "model_top5": True,
                "global_top5": True,
                "local_peer_top5": True,
            },
        ]
        metrics = prediction_metrics(rows)
        self.assertEqual(metrics["structure_group_macro"]["model_top5"], 0.5)
        self.assertAlmostEqual(metrics["target_micro"]["model_top5"], 1 / 3)

    def test_gate_scorer_applies_frozen_thresholds_and_repeat_hash(self):
        targets = [
            {
                "target_id": f"target-{index}",
                "workbook_id": f"wb-{index}",
                "structure_group": f"group-{index % 2}",
                "split": "internal_test",
                "gold_key": f"SUM A{index + 1}",
                "local_peer_top5": ["MIN A1"],
                "reachable_references": 1,
                "total_references": 1,
            }
            for index in range(4)
        ]
        predictions = [
            {"target_id": target["target_id"], "predictions": [target["gold_key"]]}
            for target in targets
        ]
        passed = score_u1_predictions(
            targets,
            ["AVERAGE A1"],
            predictions,
            repeated_prediction_hash_match=True,
            expected_structure_groups=2,
        )
        self.assertTrue(passed["passed"])
        failed_repeat = score_u1_predictions(
            targets,
            ["AVERAGE A1"],
            predictions,
            repeated_prediction_hash_match=False,
            expected_structure_groups=2,
        )
        self.assertFalse(failed_repeat["passed"])
        self.assertFalse(failed_repeat["gates"]["independent_prediction_hashes_identical"])


if __name__ == "__main__":
    unittest.main()
