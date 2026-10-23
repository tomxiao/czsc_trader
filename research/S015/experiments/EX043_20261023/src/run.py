"""Prospective fixed holding-domain successor; no retraining or score tuning."""
import argparse,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];PREV=HERE.parent/'EX042_20261023';sys.path.insert(0,str(PREV/'src'))
import accounts as a
import run_accounts as corrected
EX=a.ExperimentRef('S015',HERE.name)
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists();a.authenticate()
    prior=a.read(PREV/'others/results.json');assert len(prior['rows'])==6 and prior['qualified_centers']==0
    ref=a.material(a.ExperimentRef('S015',PREV.name),PREV/'others/results.json')
    configs=[{'family':f,'mode':m,'hold':h,'exposure':1.} for f in ('A','B') for m in ('path','risk','and') for h in (1,2,5,7)]
    protocol={'authorization':'已授权阶段三自主构造；不限研究额度，原数据与目标不变。',
      'question':'三日预测描述的信息寿命是否与固定持有不匹配？短持有降低风险和长持有减少费用的竞争解释，用同模型/信号/本金合同对照。',
      'selection_history':'EX042六组失败；最高收益B/path53.9284%但DD33.1021%，独立risk18.6926%/24.1787%。不根据单段收益重设状态，不改变训练数据、30样本/20日重训或阈值。',
      'configurations':configs,'reused_hold3':ref.to_dict(),
      'domain':'All six A/B x path/risk/and cases; hold1,2,5,7 new, hold3 existing. exposure1 fixed because all current full-risk centers lack requiredreturn; simple scaling cannot manufacture missing gross advantage. Holding integer calendar sessions not actualfilled days. No adjustable gate or stoploss added.',
      'boundary':'hold1 is minimum decision-to-next-session holding convention; hold7 provisional upper. If meaningful return/risk frontier improves toward7, expand toward9 and check maximal-frequency feasibility before longer holds; exposure1 hard no-leverage bound.',
      'methods':'Optuna queued configuration index, fourobjective full/common net/DD; public TDR evaluate_many4workers, native1,seed13. Original models/runtime source frozen inEX042; technical binding correction preserved.',
      'scope':'24newconfigurations48standardcenteraccounts; no new source/model/component; no stage4. Record every outcome and execution costs. Two independent100k windows share canonical learned coefficients and state.',
      'dependencies':a.read(PREV/'others/account_refs.json'),'binding_correction':a.read(PREV/'others/binding_correction_refs.json')}
    a.save(HERE/'protocols/accounts.json',protocol);a.save(HERE/'others/protocol_refs.json',{str(p.relative_to(HERE)).replace('\\','/'):a.material(EX,p).to_dict() for p in (HERE/'protocols/accounts.json',Path(__file__))});print('EX043_HOLDING_DOMAIN_FROZEN',flush=True)
def run():
    for key,ref in a.read(HERE/'others/protocol_refs.json').items():assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(HERE/key).read_bytes()
    for key,ref in a.read(PREV/'others/binding_correction_refs.json').items():assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(PREV/key).read_bytes()
    a.request=corrected.request;a.run(HERE.name,False)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
