from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from certified_preferences_dev22 import certified_pairs


def alt(ident, label, kind='candidate', cell='S!A1', case='c'):
    return dict(id=ident, label=label, kind=kind, cell=cell, case=case)


class CertifiedPreferencesTests(unittest.TestCase):
    def test_both_wrong_and_unknown_never_acquire_invented_preferences(self):
        rows = [alt('keep', 0, 'keep'), alt('wrong1', 0), alt('wrong2', 0), alt('unknown', None)]
        pairs, stats = certified_pairs(rows)
        self.assertEqual(pairs, [])
        self.assertEqual(stats['both_wrong_comparisons_excluded'], 3)
        self.assertEqual(stats['unknown_alternatives'], 1)
        self.assertEqual(stats['targets_without_certified_contrast'], 1)

    def test_clean_observed_formula_has_certified_direction_and_exact_mirror(self):
        rows = [alt('keep', 1, 'keep'), alt('wrong', 0), alt('also_correct', 1), alt('unknown', None)]
        pairs, stats = certified_pairs(rows)
        self.assertEqual(len(pairs), 4)
        labels = {r['id']:r['label'] for r in rows}
        for forward, reverse in zip(pairs[::2], pairs[1::2]):
            self.assertEqual((labels[forward['left_id']], labels[forward['right_id']]), (1, 0))
            self.assertEqual((forward['left_id'], forward['right_id']), (reverse['right_id'], reverse['left_id']))
            self.assertEqual((forward['label'], reverse['label']), (1, 0))
        self.assertEqual(stats['both_correct_comparisons_excluded'], 1)
        self.assertFalse(any('unknown' in (p['left_id'], p['right_id']) for p in pairs))

    def test_cap_is_per_target_keep_is_preserved_and_order_is_deterministic(self):
        rows = []
        for cell in ['S!A1', 'S!B2']:
            rows += [alt('keep', 0, 'keep', cell), alt('positive', 1, cell=cell)]
            rows += [alt(f'n{i:03}', 0, cell=cell) for i in range(100)]
        a, stats = certified_pairs(rows)
        self.assertEqual((a, stats), certified_pairs(rows[::-1]))
        self.assertEqual(stats['forward_pairs'], 2*33)
        self.assertTrue(any(p['right_id']=='keep' for p in a if p['label']==1))
        self.assertFalse(any('n032' in (p['left_id'], p['right_id']) for p in a))

    def test_missing_keep_duplicate_ids_and_invalid_states_fail_closed(self):
        cases = [[alt('a', 1), alt('b', 0)],
                 [alt('keep', 0, 'keep'), alt('keep', 1)],
                 [alt('keep', 0, 'keep'), alt('a', 2)],
                 [alt('keep', 0, 'keep'), alt('keep2', 0, 'keep')],
                 [alt('keep', 0, 'keep'), alt('a', 1, 'inferred')]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                certified_pairs(rows)
        with self.assertRaises(ValueError):
            certified_pairs([alt('keep', 1, 'keep')], -1)


if __name__ == '__main__':
    unittest.main()
