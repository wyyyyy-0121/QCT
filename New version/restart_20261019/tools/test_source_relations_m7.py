from copy import deepcopy
import unittest

from e3_contract import Unsupported
from relation_candidates_m6 import review
from source_relations_m7 import extract


class SourceEquationTests(unittest.TestCase):
    aliases = [dict(text='Original concentration', symbol='q'), dict(text='Limit', symbol='d')]
    symbols = {'q': {'units': {'concentration': 1}}, 'd': {'units': {'concentration': 1}}}

    def test_explicit_arithmetic_keeps_scale_and_operand_order(self):
        for source, expected in [('= (Original concentration/Limit) × 100 =', 50),
                                 ('= (Limit/Original concentration) * 100', 200)]:
            relation = extract(source, self.aliases, self.symbols)
            request = dict(sheet='S', cell='D1', aliases=self.aliases, symbols=self.symbols,
                           output_units={}, references={'B1': 'q', 'C1': 'd'}, relations=[relation])
            formula = '=B1/C1*100' if expected == 50 else '=C1/B1*100'
            self.assertEqual(review(request, formula, [])['reason'], 'original_satisfies_contract')

    def test_qualifiers_and_unsupported_notation_are_never_silently_dropped(self):
        for text in ['units only', '= not Original concentration/Limit',
                     '= Original concentration/Limit only if active',
                     '= (Original concentration/Limit) = 50 =', '≈ Original concentration/Limit',
                     '= ∑ Original concentration', '= 10-4 * Original concentration',
                     '= Original concentration / Unmapped', '= q/d', '= Original concentrations/Limit']:
            with self.subTest(text=text), self.assertRaises(Unsupported):
                extract(text, self.aliases, self.symbols)

    def test_duplicate_or_overlapping_aliases_reject(self):
        for aliases in [self.aliases + [dict(text='Limit', symbol='q')],
                        self.aliases + [dict(text='Original', symbol='d')]]:
            with self.assertRaises(Unsupported):
                extract('= Original concentration/Limit', aliases, self.symbols)

    def test_separated_numbers_do_not_turn_into_a_new_constant(self):
        relation = extract('= Original concentration/Limit * 1 0', self.aliases, self.symbols)
        request = dict(sheet='S', cell='D1', symbols=self.symbols, output_units={},
                       references={'B1': 'q', 'C1': 'd'}, relations=[relation])
        self.assertEqual(review(request, '=B1/C1*100', [])['status'], 'unsupported')

    def test_correct_original_and_inputs_preserved(self):
        aliases = deepcopy(self.aliases)
        relation = extract('= Original concentration/Limit * 100', aliases, self.symbols)
        self.assertEqual(aliases, self.aliases)
        request = dict(sheet='S', cell='D1', symbols=self.symbols, output_units={},
                       references={'B1': 'q', 'C1': 'd'}, relations=[relation])
        self.assertEqual(review(request, '=B1/C1*100', [])['status'], 'abstain')


if __name__ == '__main__':
    unittest.main()
