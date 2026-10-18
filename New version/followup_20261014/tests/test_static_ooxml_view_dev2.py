from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from static_ooxml_view_dev2 import create_view
import test_static_ooxml_view_dev1 as preservation_tests


class StaticPublicationTests(unittest.TestCase):
    def test_concurrent_destination_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'result.xlsx'
            def build(source, private):
                private.write_bytes(b'completed analysis')
                target.write_bytes(b'concurrent user file')
                return {'version':'fixture'}
            with patch('static_ooxml_view_dev2.build_private_view',build):
                with self.assertRaises(FileExistsError):create_view(root/'source.xlsm',target)
            self.assertEqual(target.read_bytes(),b'concurrent user file')

    def test_failure_never_publishes_partial_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'result.xlsx'
            def fail(source, private):
                private.write_bytes(b'partial');raise ValueError('build failed')
            with patch('static_ooxml_view_dev2.build_private_view',fail):
                with self.assertRaisesRegex(ValueError,'build failed'):create_view(root/'source.xlsm',target)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()),[])


class StaticViewV2Tests(preservation_tests.StaticViewTests):
    def setUp(self):
        super().setUp()
        self.replacement=patch('test_static_ooxml_view_dev1.create_view',create_view)
        self.replacement.start();self.addCleanup(self.replacement.stop)


if __name__=='__main__':unittest.main()
