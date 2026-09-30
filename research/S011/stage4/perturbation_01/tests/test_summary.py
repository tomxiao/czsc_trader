from pathlib import Path
import sys
import unittest
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from build import summarize,paired

def sample():
    rows=[]
    for center in ('S011-CFG-000618','S011-CFG-000624','S011-CFG-000621','S011-CFG-000628'):
        for i in range(47):
            for scenario in ('standard','fee_20bp'):
                rows.append(dict(center_config_id=center,kind='JOINT_HOLD13',probe=str(i),scenario=scenario,
                    design_id=i,max_days=1 if i%2 else 3,qualified=i%2==0,same_center_account=False,
                    return_pass=True,drawdown_pass=True,frequency_pass=i%2==0,frequency=6.1 if i%2 else 5.,
                    cagr=.4,drawdown_magnitude=.07,cagr_delta=-.01,drawdown_delta=.001))
    return pd.DataFrame(rows)

class SummaryTests(unittest.TestCase):
    def test_holding_strata_partition(self):
        s=summarize(sample())
        for _,g in s.groupby(['center_config_id','kind','scenario']):
            self.assertEqual(int(g[g.holding_stratum.eq('ALL')].positions.iloc[0]),int(g[~g.holding_stratum.eq('ALL')].positions.sum()))

    def test_frequency_failures_separate(self):
        s=summarize(sample());r=s[s.holding_stratum.eq('ALL')].iloc[0]
        self.assertEqual(r.frequency_above6,23);self.assertEqual(r.return_pass_count,47);self.assertEqual(r.qualified,24)

    def test_paired_offsets(self):
        p=paired(sample());self.assertEqual(len(p),376)
        self.assertTrue(p.cagr_b_minus_a.eq(0).all());self.assertTrue(p.frequency_b_minus_a.eq(0).all())

    def test_duplicate_pair_rejected(self):
        f=sample()
        with self.assertRaises(pd.errors.MergeError):paired(pd.concat([f,f.iloc[[0]]],ignore_index=True))

    def test_missing_pair_rejected(self):
        with self.assertRaises(AssertionError):paired(sample().iloc[1:])

    def test_deterioration_sign(self):
        f=sample();f.loc[f.center_config_id.eq('S011-CFG-000624'),'cagr']-=.1
        p=paired(f);g=p[p.config_b.eq('S011-CFG-000624')]
        self.assertTrue((g.cagr_b_minus_a<0).all())

if __name__=='__main__':unittest.main()
