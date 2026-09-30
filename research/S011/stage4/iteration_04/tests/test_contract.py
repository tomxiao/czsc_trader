"""Focused contract tests; no platform, external services or backtests."""
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ranking import Metric,pareto,compare,order
from build import concentration,temporal,account_metrics

class RankingTests(unittest.TestCase):
    def setUp(self):
        self.metrics=[Metric('cagr','maximize','.01'),Metric('risk','minimize','.01')]
    def test_explicit_finite_grid(self):
        for step in ('0','-1','NaN','Infinity'):
            with self.assertRaises(ValueError):Metric('x','maximize',step)
        with self.assertRaises(ValueError):Metric('x','maximize',.1)
        with self.assertRaises(ValueError):self.metrics[0].bin(float('nan'))
        self.assertEqual(self.metrics[0].bin(.015),2)
        self.assertEqual(self.metrics[0].bin(-.015),-2)
    def test_pareto_uses_only_registered_metrics(self):
        r=[{'config_id':'a','cagr':.1,'risk':.1,'frequency':4},
           {'config_id':'b','cagr':.1,'risk':.1,'frequency':6},
           {'config_id':'c','cagr':.09,'risk':.11,'frequency':5}]
        self.assertEqual(pareto(r,self.metrics)['layers'],[
            {'layer':1,'config_ids':['a','b']},{'layer':2,'config_ids':['c']}])
    def test_missing_prefix_blocks_later_metrics(self):
        r=compare({'config_id':'a','cagr':None,'risk':0},{'config_id':'b','cagr':.1,'risk':.9},self.metrics)
        self.assertEqual(r['relation'],'INCOMPARABLE')
        self.assertEqual(r['decisive_metric'],'cagr')
    def test_known_prefix_can_decide_before_missing(self):
        r=compare({'config_id':'a','cagr':.2,'risk':None},{'config_id':'b','cagr':.1,'risk':.9},self.metrics)
        self.assertEqual(r['winner'],'a')
    def test_all_known_equal_is_tie(self):
        a={'config_id':'a','cagr':.1,'risk':.1};b={**a,'config_id':'b'}
        r,p=order([a,b],[{'layer':1,'config_ids':['a','b']}],self.metrics)
        self.assertTrue(all(x['comparison_status']=='TIED' and x['recommendation_rank']==1 for x in r))
    def test_partial_rank_intervals(self):
        rows=[{'config_id':'a','cagr':.2,'risk':None},
              {'config_id':'b','cagr':.1,'risk':None},
              {'config_id':'c','cagr':.1,'risk':.1}]
        r,_=order(rows,[{'layer':1,'config_ids':['a','b','c']}],self.metrics)
        self.assertEqual([(x['rank_min'],x['rank_max']) for x in r],[(1,1),(2,3),(2,3)])
        self.assertEqual(r[0]['comparison_status'],'ORDERED')
        self.assertEqual(r[1]['comparison_status'],'PARTIAL_ORDER')
        self.assertIsNone(r[1]['recommendation_rank'])
    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):pareto([{'config_id':'a'},{'config_id':'a'}],self.metrics)

class DiagnosticTests(unittest.TestCase):
    def test_positive_closed_net_profit_and_ceiling(self):
        t=pd.DataFrame({'cycle_id':list(range(22)),'status':['CLOSED']*21+['OPEN']})
        f=pd.DataFrame({'cycle_id':list(range(22)),'side':['SELL']*22,
                        'quantity':[1]*22,'price':list(range(1,21))+[0,1000],'fees':[.5]*22})
        pnl,c=concentration(f,t,.1)
        self.assertEqual(c['positive_trades'],20);self.assertEqual(c['top_count'],2)
        self.assertAlmostEqual(c['top10pct_positive_pnl_share'],38/200)
        self.assertEqual(c['open_net_cash_flow'],999.5)
        self.assertEqual(len(pnl),21)
    def test_no_winners_not_applicable(self):
        f=pd.DataFrame({'cycle_id':[1],'side':['BUY'],'quantity':[1],'price':[10.],'fees':[1.]})
        t=pd.DataFrame({'cycle_id':[1],'status':['CLOSED']})
        self.assertIsNone(concentration(f,t,.1)[1]['top10pct_positive_pnl_share'])
    def test_rolling_includes_initial_equity(self):
        settings={'initial_cash':100.,'rolling_window':2,'rolling_step':1,'rolling_min_periods':2,'quantile_method':'linear'}
        values,q=temporal(np.array([110.,121.,133.1]),np.array([100.,100.,100.]),settings)
        np.testing.assert_allclose(values,[.21,.21],atol=1e-12)
        self.assertAlmostEqual(q,.21)
    def test_full_sample_frequency_and_initial_drawdown(self):
        a=pd.DataFrame({'equity':[90.,100.]});t=pd.DataFrame({'status':['CLOSED','OPEN']})
        r=account_metrics(a,t,100.)
        self.assertEqual(r['frequency'],30.)
        self.assertAlmostEqual(r['drawdown_magnitude'],.1)

if __name__=='__main__':unittest.main()
