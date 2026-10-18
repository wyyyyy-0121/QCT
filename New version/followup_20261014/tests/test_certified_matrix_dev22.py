from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from certified_matrix_dev22 import build_matrix, KEEP


class CertifiedMatrixTests(unittest.TestCase):
    def test_context_and_float32_differences_for_candidate_and_keep_pairs(self):
        candidates = [dict(id='a', cell='S!A1'), dict(id='b', cell='S!A1'),
                      dict(id='c', cell='S!A2')]
        values = np.array([[.1, 3], [.3, 9], [10, 11]], dtype=np.float32)
        keep = np.array([[.2, 7], [8, 9]], dtype=np.float32)
        rows = [dict(case='test', cell='S!A1', left_id='a', right_id='b'),
                dict(case='test', cell='S!A1', left_id='b', right_id='a'),
                dict(case='test', cell='S!A2', left_id='c', right_id=KEEP),
                dict(case='test', cell='S!A2', left_id=KEEP, right_id='c')]
        def load(_): return dict(candidates=candidates), values, keep, np.array([0, 0, 1])
        with tempfile.TemporaryDirectory() as tmp:
            matrix, digest = build_matrix(Path(tmp)/'m.npy', rows, 2, {'test': {}}, load)
            self.assertEqual(matrix.dtype, np.float64)
            self.assertFalse(matrix.flags.writeable)
            self.assertEqual(len(digest), 64)
            np.testing.assert_array_equal(matrix[:, :2], keep[[0, 0, 1, 1]])
            np.testing.assert_array_equal(matrix[0, 2:], values[0]-values[1])
            np.testing.assert_array_equal(matrix[2, 2:], values[2]-keep[1])
            np.testing.assert_array_equal(matrix[1, 2:], -matrix[0, 2:])
            np.testing.assert_array_equal(matrix[3, 2:], -matrix[2, 2:])

    def test_cross_target_pair_is_rejected(self):
        def load(_):
            return dict(candidates=[dict(id='bad', cell='S!A2')]), np.ones((1, 2), np.float32), np.zeros((1, 2), np.float32), np.array([0])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises((AssertionError, KeyError)):
                build_matrix(Path(tmp)/'m.npy', [dict(case='test', cell='S!A1', left_id='bad', right_id=KEEP)], 2, {'test': {}}, load)


if __name__ == '__main__': unittest.main()
