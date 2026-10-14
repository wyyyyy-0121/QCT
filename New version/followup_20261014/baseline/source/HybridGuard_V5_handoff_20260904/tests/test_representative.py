import unittest

from hybridguard.hybrid import GroupEvidence
from hybridguard.representative import representative_rows


class RepresentativeTests(unittest.TestCase):
    def _group(self, start, end):
        return GroupEvidence(
            group_id="S!I1:I2#1", sheet="S", column="I",
            start_row=start, end_row=end, size=end - start + 1,
            consensus_ratio=0.8, group_score=0.8,
            consensus_formula="=A1", source_sheet="Clean",
        )

    def test_singleton_has_one_representative(self):
        self.assertEqual(representative_rows(self._group(7, 7)), [7])

    def test_large_group_has_start_middle_end(self):
        self.assertEqual(representative_rows(self._group(10, 20)), [10, 15, 20])


if __name__ == "__main__":
    unittest.main()
