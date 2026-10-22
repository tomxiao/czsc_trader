"""Allocate the final round only after all preceding questions have completed."""
from datetime import date
from pathlib import Path
import subprocess
import sys

from suite import ROOT,HOME,SOURCE,context,save,read,material,ExperimentRef
from czsc_trader.application import create_experiment,ExperimentRequest


def main():
    for i in range(1,10):
        p=ROOT/f'research/S015/experiments/EX{15+i:03d}_20261023/others/results.json'
        assert p.exists()
        assert read(p)['qualified_centers']==0,'Use final round for qualifying-center validation instead of another mechanism'
    ex=create_experiment(context(),ExperimentRequest('放量冲击与缩量卖压的竞争解释',
        '在同一卖压反转机制下，既有20日成交额状态能否区分短暂流动性冲击与持续下跌？',date(2026,10,23)))
    assert ex==ExperimentRef('S015','EX025_20261023')
    here=ex.resolve(ROOT)
    original=(SOURCE/'strategies/pressure_path.py').read_text(encoding='utf-8')
    code=original.replace("'base': {}, 'cross': {},", "'volume_high': {}, 'volume_low': {}, 'base': {}, 'cross': {},",1)
    old="        pressure = m.Close/(m.Amount/m.Volume)-1\n"
    new=old+"        amount = np.log(m.Amount)\n        liquidity = ((amount-amount.rolling(20).mean())/amount.rolling(20).std(ddof=0)\n                     if mode in ('volume_high','volume_low') else pd.Series(0.,index=m.index))\n"
    assert old in code
    code=code.replace(old,new,1)
    old="'range':ranges,'average':pressure.rolling(lb).mean()"
    assert old in code
    code=code.replace(old,"'range':ranges,'average':pressure.rolling(lb).mean(),'liquidity':liquidity",1)
    old="                elif mode=='price_confirm':\n"
    assert old in code
    code=code.replace(old,"                elif mode=='volume_high':\n                    enter = enter and v.liquidity>=0\n                elif mode=='volume_low':\n                    enter = enter and v.liquidity<0\n"+old,1)
    source=here/'src/strategy_runtime/strategies/pressure_path.py'
    source.parent.mkdir(parents=True,exist_ok=True)
    source.write_text(code,encoding='utf-8',newline='\n')
    for name in ('suite.py','check_signals.py'):
        (here/'src'/name).write_bytes((HOME/'src'/name).read_bytes())
    subprocess.run([sys.executable,str(here/'src/check_signals.py')],cwd=ROOT,check=True)
    base={'entry':0.,'exit':.005,'hold':3}
    protocol={'round':10,'title':'放量冲击与缩量卖压的竞争解释',
        'hypothesis':'EX002已有量价统计与复杂组负面证据保留；当前顺序、确认、趋势、振幅等问题失败后，固定检验尚未独立回答的成交额状态与卖压条件交互，不宣称新组件已有效。',
        'definition':'amount_z20=(log(Amount)-rolling20mean(log(Amount)))/rolling20std(ddof0)，与EX002既有定义一致。当前自然正负边界，两方向都保留；未知/退化标准差直接失败，不填0。',
        'configurations':[{'mode':m,**base} for m in ('base','volume_high','volume_low')],
        'controls':'Same pressure entry/exit/hold and exact trading contract. Separate first-entry permission by sign of known same-day amount_z20; no change to active position/exit logic.',
        'budget':{'configurations':3,'scenarios':6,'remaining_after_this':0},
        'stopping':'Final authorized round. No volume threshold/length tuning after outcomes. Existing nonpassing candidates cannot be promoted and no extra round is automatically started.',
        'selection':'All prior results known, no new independent sample or source. If no dual-qualified center, end budget and publish empty new-goal handoff; no32point/stress computations for failed centers.'}
    save(here/'protocols/round.json',protocol)
    refs=[material(ex,name,p).to_dict() for name,p in (
        ('round_protocol',here/'protocols/round.json'),('pressure_path',source),
        ('execution_suite_v4',here/'src/suite.py'),('signal_checks',here/'others/signal_checks.json'),
        ('signal_check_source',here/'src/check_signals.py'),('tenth_round_design',Path(__file__)),
        ('prior_volume_definition',ROOT/'research/S015/experiments/EX002_20261021/src/component_study.py'))]
    save(here/'others/protocol_refs.json',refs)
    print({'experiment':ex.experiment_id,'round':10,'protocol':'PUBLISHED'},flush=True)


if __name__=='__main__':
    main()
