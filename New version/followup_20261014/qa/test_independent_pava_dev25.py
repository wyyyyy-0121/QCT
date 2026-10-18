from pathlib import Path
import sys
import unittest
import numpy as np
from sklearn.isotonic import IsotonicRegression
sys.path.insert(0,str(Path(__file__).resolve().parent))
from audit_nested_calibration_dev25 import pava


class IndependentPavaTests(unittest.TestCase):
    def test_repeated_scores_weighted_decreasing_blocks_and_endpoints(self):
        x=[.1,.1,.2,.3,.4,.5,.5];y=[0,1,1,0,0,1,0];w=[1,3,2,4,1,2,1]
        xs,ys=pava(x,y,w);model=IsotonicRegression(out_of_bounds='nan').fit(x,y,sample_weight=w)
        np.testing.assert_allclose(ys,model.predict(xs),atol=1e-14)
        self.assertTrue(np.all(np.diff(ys)>=0))

    def test_deterministic_weighted_binary_cases(self):
        rng=np.random.default_rng(251018)
        for _ in range(50):
            x=rng.integers(0,20,100)/20;y=rng.integers(0,2,100);w=rng.uniform(.01,2,100)
            xs,ys=pava(x,y,w);model=IsotonicRegression().fit(x,y,sample_weight=w)
            np.testing.assert_allclose(ys,model.predict(xs),atol=1e-13)


if __name__=='__main__':unittest.main()
