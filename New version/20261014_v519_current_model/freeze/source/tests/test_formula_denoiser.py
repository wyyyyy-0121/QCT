import unittest

import torch

from formulaguard.formula_denoiser import FormulaDenoiser, denoising_source
from formulaguard.pcrc import PCRCVocabulary
from scripts.train_formula_denoiser_pilot import (
    DenoisingDataset,
    FormulaBase,
    canonical_generated,
    masked_reference_corruption,
    peer_formula_bodies,
    peer_mode_prediction,
)


class FormulaDenoiserTests(unittest.TestCase):
    def test_reference_masking_is_deterministic_and_changes_one_token(self):
        tokens = ("REF", "SELF", "ROW_REL", "OFFSET_NEG", "DIGIT_2")
        first = masked_reference_corruption(tokens, target_id="target")
        second = masked_reference_corruption(tokens, target_id="target")
        self.assertEqual(first, second)
        self.assertIsNotNone(first)
        self.assertEqual(sum(left != right for left, right in zip(tokens, first)), 1)
        self.assertIn("<MASK>", first)

    def test_source_preserves_context_and_corrupted_formula_segments(self):
        source, segments = denoising_source((2, 4, 3), (2, 5, 3), maximum_length=6)
        self.assertEqual(source, (2, 4, 3, 2, 5, 3))
        self.assertEqual(segments, (0, 0, 0, 1, 1, 1))
        with self.assertRaises(ValueError):
            denoising_source((2, 4, 3), (2, 5, 3), maximum_length=5)

    def test_transformer_masks_non_formula_outputs(self):
        model = FormulaDenoiser(
            8,
            allowed_output_ids=(3, 4, 5),
            maximum_source_length=8,
            maximum_target_length=6,
            model_size=16,
            attention_heads=4,
            encoder_layers=1,
            decoder_layers=1,
            feedforward_size=32,
            dropout=0.0,
        )
        source = torch.tensor([[2, 4, 3, 2, 5, 3]])
        segments = torch.tensor([[0, 0, 0, 1, 1, 1]])
        logits = model(source, segments, torch.tensor([[2, 4]]))
        self.assertEqual(tuple(logits.shape), (1, 2, 8))
        self.assertTrue(torch.isneginf(logits[..., 0]).all())
        self.assertTrue(torch.isfinite(logits[..., 3:6]).all())

    def test_copy_alignment_skips_context_and_formula_start(self):
        model = FormulaDenoiser(
            8,
            maximum_source_length=8,
            maximum_target_length=6,
            model_size=16,
            attention_heads=4,
            encoder_layers=1,
            decoder_layers=1,
            feedforward_size=32,
            dropout=0.0,
        )
        aligned = model.aligned_copy_ids(
            torch.tensor([[2, 4, 3, 2, 5, 6, 3, 0]]),
            torch.tensor([[0, 0, 0, 1, 1, 1, 1, 0]]),
            4,
        )
        self.assertEqual(aligned.tolist(), [[5, 6, 3, 0]])

    def test_beam_generation_stops_at_end_token(self):
        model = FormulaDenoiser(
            8,
            allowed_output_ids=(3,),
            maximum_source_length=8,
            maximum_target_length=6,
            model_size=16,
            attention_heads=4,
            encoder_layers=1,
            decoder_layers=1,
            feedforward_size=32,
            dropout=0.0,
        )
        sequences, scores = model.beam_generate(
            torch.tensor([[2, 4, 3, 2, 5, 3]]),
            torch.tensor([[0, 0, 0, 1, 1, 1]]),
            start_id=2,
            end_id=3,
            beam_size=1,
        )
        self.assertEqual(tuple(sequences.shape), (1, 1, 2))
        self.assertEqual(sequences[0, 0].tolist(), [2, 3])
        self.assertEqual(tuple(scores.shape), (1, 1))

    def test_dataset_leaves_unselected_mutation_family_out(self):
        base = FormulaBase(
            target_id="target",
            workbook_id="workbook",
            structure_group="group",
            context_ids=(2, 4, 3),
            clean_ids=(2, 5, 3),
            corruptions={"operator": (2, 6, 3), "reference_offset": (2, 7, 3)},
        )
        dataset = DenoisingDataset((base,), ("operator",), include_clean=True)
        self.assertEqual([dataset[index][1] for index in range(len(dataset))], [
            "clean", "operator"
        ])

    def test_peer_mode_uses_formula_bodies_not_direction_metadata(self):
        vocabulary = PCRCVocabulary((
            "<PAD>", "<UNK>", "<START>", "<END>",
            "CTX", "PEER_START", "DIR_UP", "DIST_1", "FORMULA_A", "FORMULA_B",
            "PEER_END", "CTX_END",
        ))
        context = vocabulary.encode((
            "CTX",
            "PEER_START", "DIR_UP", "DIST_1", "FORMULA_A", "PEER_END",
            "PEER_START", "DIR_UP", "DIST_1", "FORMULA_A", "PEER_END",
            "PEER_START", "DIR_UP", "DIST_1", "FORMULA_B", "PEER_END",
            "CTX_END",
        ), maximum=32)
        base = FormulaBase(
            target_id="target",
            workbook_id="workbook",
            structure_group="group",
            context_ids=context,
            clean_ids=vocabulary.encode(("FORMULA_A",), maximum=8),
            corruptions={"operator": vocabulary.encode(("FORMULA_B",), maximum=8)},
        )
        self.assertEqual(peer_formula_bodies(context, vocabulary), [
            (vocabulary.ids["FORMULA_A"],),
            (vocabulary.ids["FORMULA_A"],),
            (vocabulary.ids["FORMULA_B"],),
        ])
        predicted = peer_mode_prediction(
            base,
            base.corruptions["operator"],
            {},
            vocabulary,
        )
        self.assertEqual(predicted, base.clean_ids)
        self.assertEqual(canonical_generated((*predicted, 0, 0), end_id=3), predicted)


if __name__ == "__main__":
    unittest.main()
