from pathlib import Path
import sys
import math
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from ranking import Metric, rank, group_behaviors
from verify import independent_bin
from build import Decision


class RankingTests(unittest.TestCase):
    def test_metric_contract(self):
        for args in [('x', 'sideways', '.1'), ('x', 'maximize', '0'), ('x', 'maximize', 'NaN'), ('x', 'maximize', '-1')]:
            with self.assertRaises(ValueError):
                Metric(*args)

    def test_half_up_and_negative_boundary(self):
        m = Metric('x', 'maximize', '.1')
        for v, expected in [(0.049, 0), (.05, 1), (-.05, -1), (.15, 2), (-.15, -2), (0, 0)]:
            self.assertEqual(m.bin(v), expected)
            self.assertEqual(independent_bin(v, '.1', '0'), expected)

    def test_shifted_grid(self):
        m = Metric('x', 'maximize', '.1', '.05')
        self.assertEqual(m.bin(.099), 0); self.assertEqual(m.bin(.1), 1)

    def test_boundary_is_not_pairwise_tolerance(self):
        m = Metric('x', 'maximize', '.1')
        self.assertNotEqual(m.bin(.0499), m.bin(.0501))

    def test_ties_and_directions(self):
        rows = [{'config_id': 'a', 'r': 1., 'd': .2}, {'config_id': 'b', 'r': 1., 'd': .3},
                {'config_id': 'c', 'r': .9, 'd': .1}, {'config_id': 'd', 'r': 1.001, 'd': .201}]
        result = rank(rows, [Metric('r', 'maximize', '.1'), Metric('d', 'minimize', '.1')])
        self.assertEqual(result['layers'][0]['config_ids'], ['a', 'c', 'd'])
        self.assertEqual(result['layers'][1]['config_ids'], ['b'])

    def test_missing_nan_bool_not_zero(self):
        rows = [{'config_id': 'a', 'r': None}, {'config_id': 'b', 'r': math.nan},
                {'config_id': 'c', 'r': False}, {'config_id': 'd', 'r': 0.}]
        result = rank(rows, [Metric('r', 'maximize', '.1')])
        self.assertEqual(set(result['unranked']), {'a', 'b', 'c'})
        self.assertEqual(result['layers'][0]['config_ids'], ['d'])

    def test_duplicate_ids_and_metrics(self):
        with self.assertRaises(ValueError):
            rank([{'config_id': 'a'}, {'config_id': 'a'}], [Metric('r', 'maximize', '.1')])
        with self.assertRaises(ValueError):
            rank([], [Metric('r', 'maximize', '.1')]*2)
        with self.assertRaises(ValueError):
            rank([], [])

    def test_empty_population(self):
        self.assertEqual(rank([], [Metric('r', 'maximize', '.1')])['layers'], [])

    def test_group_does_not_borrow_pressure_or_hide_members(self):
        rows = [{'config_id': 'a', 'behavior_id': 'b1', 'fee20_cagr': .3},
                {'config_id': 'b', 'behavior_id': 'b1', 'fee20_cagr': math.nan},
                {'config_id': 'c', 'behavior_id': 'b1', 'fee20_cagr': .2}]
        ranked = rank(rows, [Metric('fee20_cagr', 'maximize', '.01')])
        definitions = {r['config_id']: {'definition': {'parameters': {'x': i}, 'runtime': {'source_sha256': str(i)}}} for i, r in enumerate(rows)}
        g = group_behaviors(rows, ranked, definitions)[0]
        self.assertEqual(g['config_ids'], ['a', 'b', 'c']); self.assertEqual(g['unranked_members'], ['b'])
        self.assertEqual(g['fee20_status'], 'PARTIAL'); self.assertEqual(g['fee20_cagr_range'], [.2, .3])
        self.assertEqual(g['member_layers'], {'a': 1, 'b': None, 'c': 2})

    def test_permutation_invariance(self):
        rows = [{'config_id': str(i), 'r': i/10, 'd': i/20} for i in range(10)]
        m = [Metric('r', 'maximize', '.1'), Metric('d', 'minimize', '.1')]
        self.assertEqual(rank(rows, m), rank(list(reversed(rows)), m))

    def test_no_automatic_approval(self):
        with self.assertRaises(ValueError):
            Decision(selected_config_ids=['S011-CFG-000624'])


if __name__ == '__main__':
    unittest.main()
