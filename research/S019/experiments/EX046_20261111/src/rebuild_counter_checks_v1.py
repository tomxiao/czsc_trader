"""Synthetic counter probes: actual restoration, zero-target latch and cycle reset."""
from hashlib import sha256
import json
from pathlib import Path
import runpy

WORK = Path(__file__).resolve().parents[1]
SOURCE = WORK/'src/compare_rebuild.py'
analyze = runpy.run_path(str(SOURCE),run_name='counter_probe')['risk_dynamics']


def decision(name,time,fraction,target):
    return {'decision_id':name,'execution_start':'2024-01-02T'+time+'Z','target':target,
            'explanation':{'basis':[{'key':'risk_fraction','text':str(fraction)}]}}


def run(fill_specs,decisions):
    fills = [{'cycle_id':cid,'executed_at':'2024-01-02T'+time+'Z','side':side,
              'quantity':quantity,'price':100.,'fees':1.,'order_id':name}
             for cid,name,time,side,quantity in fill_specs]
    return {'fills':fills,'orders':[{'order_id':f['order_id'],'decision_id':f['order_id']} for f in fills],
            'trades':[{'cycle_id':cid,'status':'CLOSED','net_return':-.01,'net_pnl':-100.}
                      for cid in sorted({f['cycle_id'] for f in fills})],
            'decisions':decisions,
            'account_points':[{'time':'2024-01-02T'+time+'Z','equity':equity} for time,equity in
                              [('09:59:00',10000.),('10:29:00',9900.),('10:59:00',9800.),
                               ('11:29:00',9850.),('11:59:00',9900.),('12:29:00',9950.),
                               ('12:59:00',9900.),('13:29:00',10000.)]]}


restored = analyze(run([('a','entry','10:00:00','BUY',100),('a','rebalance','10:15:00','BUY',5),
                        ('a','cut','10:30:00','SELL',50),('a','restore','11:00:00','BUY',20),
                        ('a','exit','11:30:00','SELL',75)],
                       [decision('rebalance','10:15:00',1.,.6),decision('cut','10:30:00',.5,.3),
                        decision('restore','11:00:00',.8,.48),
                        decision('exit','11:30:00',0.,0.)]))
assert restored['risk_increase_decisions']==restored['actual_restore_buy_fills']==1
assert abs(restored['mean_closed_cycle_fees_over_entry_equity']-.0005)<1e-12
assert restored['cycles'][0]['restore_buy_fees_over_entry_equity']==.0001
assert abs(restored['cycles'][0]['post_first_restore_marked_account_return']-(9900/9800-1))<1e-12
latched = analyze(run([('a','entry','10:00:00','BUY',100),('a','exit','11:30:00','SELL',100),
                       ('b','entry_b','12:00:00','BUY',100),('b','exit_b','13:00:00','SELL',100)],
                      [decision('trigger','10:30:00',0.,0.),decision('latched_recovery','11:00:00',1.,0.),
                       decision('exit','11:30:00',0.,0.),decision('new_cycle_hold','12:30:00',1.,.6),
                       decision('exit_b','13:00:00',0.,0.)]))
assert latched['risk_increase_decisions']==latched['actual_restore_buy_fills']==0
out = {'status':'PASS','new_accounts':0,'analysis_source_sha256':sha256(SOURCE.read_bytes()).hexdigest(),
       'verification_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
       'checks':['fraction increase linked to actual BUY','constant-target BUY excluded by decision linkage',
                 'zero-target exiting latch excludes fraction recovery','new cycle starts with fraction one',
                 'fees normalized by entry equity','post-restore marked equity interval'],
       'restoration_fixture':{k:restored[k] for k in ('risk_increase_decisions','actual_restore_buy_fills','mean_closed_cycle_fees_over_entry_equity')},
       'latched_new_cycle_fixture':{k:latched[k] for k in ('risk_increase_decisions','actual_restore_buy_fills')}}
(WORK/'others/rebuild_counter_checks.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
print('REBUILD_COUNTER_PROBES_PASS',out['analysis_source_sha256'])
