"""Checks for truthful effective concurrency and baseline comparison."""
import unittest

from scale_spreadsheetbench2_resources import admission, differences


class ResourceScalingTests(unittest.TestCase):
    def test_admission_rejects_silent_downgrade(self):
        with self.assertRaises(ValueError):
            admission(12 * 1024**3)
        self.assertEqual(admission(13.1 * 1024**3)['requested_workers'], 16)

    def test_comparison_detects_timeout_and_hash_differences(self):
        def runtime(status, digest):
            return {'tasks': [{'id': 'a', 'status': status,
                               'returncode': 0 if status == 'complete' else -15,
                               'output_sha256': {'prediction.json': digest}}]}
        before = runtime('complete', 'a')
        self.assertFalse(differences(before, before))
        self.assertIn('a', differences(before, runtime('complete', 'b')))
        self.assertIn('a', differences(before, runtime('timeout', None)))

    def test_comparison_rejects_missing_task(self):
        with self.assertRaises(ValueError):
            differences({'tasks': []}, {'tasks': [{'id': 'a', 'status': 'timeout',
                        'returncode': -15, 'output_sha256': {}}]})


if __name__ == '__main__':
    unittest.main()
