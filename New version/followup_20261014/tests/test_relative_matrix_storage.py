"""Verify recovered training preserves data and the fitted estimator, not just shape."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from relative_matrix_storage import build_matrix
from relative_learning_dev21 import representation, infer
from candidate_features_dev16 import PARAMETERS


class MatrixStorageTests(unittest.TestCase):
    def test_exact_float32_rounding_order_weights_model_and_suggestions(self):
        rng = np.random.default_rng(321)
        values = rng.normal(size=(160, 7)).astype(np.float32)
        keep = rng.normal(size=(80, 7)).astype(np.float32)
        values[:, -3:] = 0
        keep[:, -3:] = 0
        offsets = np.repeat(np.arange(80), 2)
        candidates = [{'id': str(i), 'cell': f'S!A{i//2+1}',
                       'formula': f'={i+2}', 'eligible': True} for i in range(160)]
        payload = {'candidates': candidates, 'baseline': []}
        selected = list(rng.permutation(160))
        rows = [{'case': 'a', 'id': str(i)} for i in selected]
        y0 = (values[selected, 0] > keep[offsets[selected], 0]).astype(np.int8)
        y = np.r_[y0, 1-y0]
        w = np.tile(rng.uniform(.1, 3, len(rows)), 2)
        old = np.concatenate([representation(values[selected], keep[offsets[selected]]),
                              representation(values[selected], keep[offsets[selected]], reverse=True)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'matrix.npy'
            x, digest = build_matrix(path, rows, 7, {'a': None},
                                      lambda item: (payload, values, keep, offsets))
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(x.dtype, np.float64)
            self.assertFalse(x.flags.writeable)
            np.testing.assert_array_equal(x, old.astype(np.float64))
            expected = HistGradientBoostingClassifier(**PARAMETERS).fit(old, y, sample_weight=w)
            actual = HistGradientBoostingClassifier(**PARAMETERS).fit(x, y, sample_weight=w)
            validated = actual._preprocess_X(x, reset=False)
            self.assertTrue(np.shares_memory(x, validated))
            np.testing.assert_array_equal(expected.predict_proba(old), actual.predict_proba(old))
            names = ['unit_new_compatible', 'unit_new_incompatible', 'unit_new_unknown']
            p1, s1 = infer(expected, payload, values, keep, offsets, names)
            p2, s2 = infer(actual, payload, values, keep, offsets, names)
            np.testing.assert_array_equal(p1, p2)
            self.assertEqual(s1, s2)
            del validated, x

    def test_missing_candidate_and_non_float32_features_are_rejected(self):
        payload = {'candidates': [{'id': 'present'}]}
        k = np.ones((1, 2), dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'matrix.npy'
            with self.assertRaises(AssertionError):
                build_matrix(p, [{'case': 'a', 'id': 'missing'}], 2, {'a': None},
                             lambda item: (payload, k, k, np.array([0])))
            with self.assertRaises(AssertionError):
                build_matrix(p, [{'case': 'a', 'id': 'present'}], 2, {'a': None},
                             lambda item: (payload, k.astype(np.float64), k, np.array([0])))


if __name__ == '__main__':
    unittest.main()
