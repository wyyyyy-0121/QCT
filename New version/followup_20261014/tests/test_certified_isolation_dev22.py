from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]


class CertifiedIsolationTests(unittest.TestCase):
    def run_isolated(self, body):
        result = subprocess.run([sys.executable, '-c', "import sys\nsys.path.insert(0, 'scripts')\nimport run_certified_learning_dev22 as m\n"+body],
                                cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_learner_preflight_does_not_open_author_or_fold_label_bodies(self):
        self.run_isolated("""
active = m.protect_preflight()
m.verify_features()
m.verify_preparation()
try: m.verify_preparation(include_label_bodies=True)
except PermissionError: pass
else: raise AssertionError('author audit must require explicit label-body access')
active[0] = False
""")

    def test_guard_denies_author_and_other_fold_but_accepts_current_fold(self):
        self.run_isolated("""
active, accesses, allowed, reads = m.protect_training()
folds = m.read(m.LABELS/'fold_index.json')['folds']
current = m.LABELS/folds[0]['train_label_file']
allowed[0] = str(current.resolve())
for p in [m.LABELS/'author_case_states/test.json.gz', m.LABELS/'author_case_pairs/test.json.gz',
          m.LABELS/folds[1]['train_label_file'], m.BASE/'heldout_truth.json.gz', m.BASE/'case_labels/test.json.gz']:
    try: p.open('rb')
    except PermissionError: pass
    else: raise AssertionError(str(p))
with current.open('rb') as handle: assert len(handle.read(1)) == 1
assert reads == {str(current.resolve())}
active[0] = False
""")


if __name__ == '__main__': unittest.main()
