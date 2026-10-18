"""Tests for output isolation, failed task retention and process-tree timeout."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

import batch_runner


class RunnerTest(unittest.TestCase):
    def run_tasks(self, root, rows, workers=2):
        path = root / "manifest.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return batch_runner.run(argparse.Namespace(manifest=path, output_dir=root / "run",
            cwd=None, workers=workers, timeout=5, thread_limit=1))

    def test_output_isolation_and_thread_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = "import os,pathlib; pathlib.Path('result.txt').write_text(os.environ['OPENBLAS_NUM_THREADS'])"
            result = self.run_tasks(root, [dict(id=name, argv=[sys.executable, "-c", script],
                 outputs=["result.txt"]) for name in ("one", "two")])
            self.assertTrue(result["all_tasks_complete"])
            self.assertEqual((root / "run/tasks/one/result.txt").read_text(), "1")
            self.assertEqual(result["tasks"][0]["output_sha256"], result["tasks"][1]["output_sha256"])
            self.assertFalse((root / "result.txt").exists())
            self.assertTrue(result["cpu_accounting_complete"])

    def test_failed_and_timeout_remain_in_result(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_tasks(Path(folder), [
                dict(id="failed", argv=[sys.executable, "-c", "raise SystemExit(7)"]),
                dict(id="timeout", argv=[sys.executable, "-c", "import time; time.sleep(5)"],
                     timeout_seconds=0.1)])
            self.assertFalse(result["all_tasks_complete"])
            self.assertEqual([row["status"] for row in result["tasks"]], ["failed", "timeout"])
            self.assertEqual(result["task_count"], 2)

    def test_unsafe_or_duplicate_task_ids_rejected(self):
        for names in (("../escape",), ("same", "same")):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with self.assertRaises(ValueError):
                    self.run_tasks(root, [dict(id=name, argv=["true"]) for name in names])
                self.assertFalse((root / "run").exists())

    def test_existing_output_directory_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "run").mkdir()
            marker = root / "run/keep.txt"
            marker.write_text("original")
            with self.assertRaises(SystemExit):
                self.run_tasks(root, [dict(id="a", argv=["true"])])
            self.assertEqual(marker.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
