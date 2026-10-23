"""Prospective forecast-permission exit, compared with frozen fixed holding."""
import argparse,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];PREV=HERE.parent/'EX042_20261023';sys.path.insert(0,str(PREV/'src'))
import accounts as a
import run_accounts as corrected
EX=a.ExperimentRef('S015',HERE.name)
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists();a.authenticate()
    assert a.read(HERE/'others/runtime_checks.json')['status']=='PASS'
    protocol={'authorization':'阶段三已授权，自主实验额度不限，既定目标和数据不变。',
      'question':'固定持有可能忽略新的风险或机会信息；当原入场许可失效时，下一交易日退出能否改善收益回撤取舍？',
      'selection_history':'EX042/43固定持有30配置均未过联合中心；A-risk7与A-and7仅过434中心。EX042高收益B-path首日贡献大，EX043 A-risk7后续贡献大，故不先假定提早退出有利。',
      'configurations':[{'family':f,'mode':m,'hold':h,'exposure':1.,'exit_rule':'permission'} for f in ('A','B') for m in ('path','risk','and') for h in (3,7)],
      'state':'收盘作决定，次日执行；在持仓意图周期若age>=hold或当日当前mode许可为false则目标0，退出当日不重新进入；空闲且许可true才新周期。退出由已知预测决定，不能阻止已发生的当日亏损。',
      'controls':'EX042 hold3与EX043 hold7的同家族同mode固定持有共12配置原证据复用；新源fixed模式逐字段等同旧源，permission只改变退出状态机。',
      'domain':'固定3/7持有上限，唯一新类别permission exit；不调模型、训练时钟、许可阈值或仓位。若边界改善，根据频率/归因另立协议验证。',
      'methods':'Optuna固定排队、TDR4进程/原生1/seed13；首配置串行与并行双窗口5账本/hash比对。',
      'scope':'12新配置24正式账户场景，2技术重复场景；同434/415独立10万元，同限价、手续费与现金周期；无阶段四。',
      'controls_results':[a.material(a.ExperimentRef('S015',ex),HERE.parent/ex/'others/results.json').to_dict() for ex in ('EX042_20261023','EX043_20261023')],
      'dependencies':a.read(PREV/'others/account_refs.json'),'binding_correction':a.read(PREV/'others/binding_correction_refs.json')}
    a.save(HERE/'protocols/accounts.json',protocol)
    paths=[Path(__file__),HERE/'protocols/accounts.json',HERE/'src/strategy_runtime/strategies/price_information.py',HERE/'src/check_exit.py',HERE/'others/runtime_checks.json']
    a.save(HERE/'others/protocol_refs.json',{p.relative_to(HERE).as_posix():a.material(EX,p).to_dict() for p in paths});print('EX045_EXIT_DESIGN_FROZEN',flush=True)
def run():
    for key,ref in a.read(HERE/'others/protocol_refs.json').items():assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(HERE/key).read_bytes()
    for key,ref in a.read(PREV/'others/binding_correction_refs.json').items():assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(PREV/key).read_bytes()
    a.SOURCE=HERE/'src/strategy_runtime';a.request=corrected.request;a.run(HERE.name,True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
