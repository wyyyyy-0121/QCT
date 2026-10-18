"""Guard metadata provenance and detect source mutation despite unchanged lock."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from peer_metadata_dev8 import corrected_index, assert_parallel_sheets
import run_selector_dev8 as runner


class MetadataTests(unittest.TestCase):
    def test_regression_uses_public_metadata_without_mutating_input(self):
        original = [{'id':'single', 'group':'regression', 'parallel_sheets':list('ABCDE')}]
        reads = []
        def read(path):
            reads.append(path)
            return {'parallel_sheets':['North']}
        output = corrected_index(Path('/root'), original, read, lambda _:'digest')
        self.assertEqual(output[0]['parallel_sheets'], ['North'])
        self.assertEqual(output[0]['parallel_metadata'], 'baseline/data/single/public.json')
        self.assertEqual(output[0]['parallel_metadata_sha256'], 'digest')
        self.assertEqual(original[0]['parallel_sheets'], list('ABCDE'))
        self.assertEqual(reads,[Path('/root/baseline/data/single/public.json')])

    def test_non_regression_is_not_reinterpreted(self):
        original = [{'id':'a', 'group':'stress', 'parallel_sheets':['Region']}]
        def forbidden(_):
            raise AssertionError('non-regression metadata unexpectedly read')
        self.assertEqual(corrected_index(Path('/root'), original, forbidden, forbidden), original)

    def test_invalid_metadata_is_rejected(self):
        for names in [[], ['North','North'], 'North', [None], [''], [{}]]:
            with self.subTest(names=names), self.assertRaises(ValueError):
                corrected_index(Path('/root'), [{'id':'x','group':'regression','parallel_sheets':[]}],
                                lambda _: {'parallel_sheets':names}, lambda _:'digest')

    def test_absent_declared_sheet_fails_instead_of_silent_fallback(self):
        model = SimpleNamespace(formulas={('North','A2'):'=1'})
        assert_parallel_sheets(model,['North'])
        with self.assertRaisesRegex(ValueError,'A, B'):
            assert_parallel_sheets(model,['A','B'])

    def test_changed_source_is_detected_when_source_lock_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); run=root/'run'; run.mkdir()
            source=root/'selector.py'; source.write_text('original')
            runner.save(run/'source_lock.json', {'files':{'selector.py':runner.sha(source)}})
            runner.save(run/'public_index.json', [])
            lock={'source_lock_sha256':runner.sha(run/'source_lock.json'),
                  'public_index_sha256':runner.sha(run/'public_index.json'),
                  'files':{}, 'inputs_and_upstream':{}, 'labels_read':[],
                  'final_validation_eligible':False}
            with patch.object(runner,'ROOT',root), patch.object(runner,'RUN',run):
                runner.verify_inputs(lock)
                source.write_text('mutated')
                with self.assertRaises(AssertionError):
                    runner.verify_inputs(lock)


if __name__ == '__main__':
    unittest.main()
