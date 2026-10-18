"""Regression checks for experiment terminal-state and output-lock validation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "resume_sbb2", Path(__file__).with_name("resume_spreadsheetbench2_after_pilot.py"))
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


class LockValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.jsonl"
        self.manifest.write_text(json.dumps({"id": "task", "argv": ["python"]}) + "\n")
        self.output = self.root / "prediction.json"
        self.task = {"id": "task", "cwd": str(self.root), "status": "timeout",
                     "returncode": -15, "output_sha256": {"prediction.json": None}}

    def validate(self):
        resume.validate_runtime({"tasks": [self.task]}, self.manifest)

    def test_timeout_without_output_is_valid_but_not_complete(self):
        self.validate()
        self.assertEqual(resume.task_signature({"tasks": [self.task]})["task"],
                         ("timeout", -15, None))

    def test_complete_requires_present_unchanged_output(self):
        self.task.update(status="complete", returncode=0)
        with self.assertRaises(SystemExit):
            self.validate()
        self.output.write_text('{}\n')
        self.task["output_sha256"]["prediction.json"] = resume.sha256(self.output)
        self.validate()
        self.output.write_text('{"changed":true}\n')
        with self.assertRaises(SystemExit):
            self.validate()

    def test_timeout_cannot_supply_prediction(self):
        self.output.write_text('{}\n')
        with self.assertRaises(SystemExit):
            self.validate()

    def test_missing_or_duplicate_terminal_records_are_rejected(self):
        for tasks in ([], [self.task, self.task]):
            with self.assertRaises(SystemExit):
                resume.validate_runtime({"tasks": tasks}, self.manifest)


if __name__ == "__main__":
    unittest.main()
