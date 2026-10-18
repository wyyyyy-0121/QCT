"""Post-lock cv-500 correction diff with independent OOXML inventory check."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'qa'),str(ROOT/'scripts')]
import diff_hobyah_natural_dev26 as diff
import run_cv500_natural_dev27 as runner

if __name__=='__main__':
    diff.RUN=runner.RUN;diff.verify=runner.engine.verify;diff.main()
