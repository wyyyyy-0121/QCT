import unittest

from hybridguard.metrics import average_precision, top_k_stats


class MetricTests(unittest.TestCase):
    def test_average_precision(self):
        self.assertAlmostEqual(
            average_precision(["a", "b", "c", "d"], {"a", "c"}),
            (1 + 2 / 3) / 2,
        )

    def test_top_k(self):
        self.assertEqual(top_k_stats(["a", "b", "c"], {"a", "c"}, 2)["hits"], 1)


if __name__ == "__main__":
    unittest.main()
