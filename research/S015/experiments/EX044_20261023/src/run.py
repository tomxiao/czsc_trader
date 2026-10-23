"""Prospective extension of the improving A-family holding boundary."""
import argparse,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];PREV=HERE.parent/'EX042_20261023';sys.path.insert(0,str(PREV/'src'))
import accounts as a
import run_accounts as corrected
EX=a.ExperimentRef('S015',HERE.name)
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists();a.authenticate()
    prior=HERE.parent/'EX043_20261023/others/results.json'
    assert a.read(prior)['qualified_centers']==0
    protocol={'authorization':'阶段三已授权，自主额度不限，原目标和数据不变。',
      'question':'A族持有7日边界仍改善，延长至9日是否继续改善收益回撤，真实交易频率代价是什么？',
      'selection_history':'EX043 A-risk7净56.5342%、回撤16.5383%，A-and7净50.8556%、回撤22.1771%；两者通过434中心但未过415双门。A-path7也改善于5日。B7未改善对应收益回撤前沿，暂不延伸B。',
      'configurations':[{'family':'A','mode':m,'hold':9,'exposure':1.} for m in ('path','risk','and')],
      'boundary':'9日是本轮临时上界。若继续产生有意义前沿改善，结合真实60日闭合频率决定进一步延伸；不把未测试更长持有自动判为失败。',
      'methods':'Optuna固定排队，公开TDR四进程、原生线程1、seed13；EX042原模型和运行时及身份修正不变。',
      'scope':'3新配置6标准中心账户；复用EX042/43对照，无新组件或训练、阈值、仓位搜索；未进入阶段四。',
      'prior_results':a.material(a.ExperimentRef('S015','EX043_20261023'),prior).to_dict(),
      'dependencies':a.read(PREV/'others/account_refs.json'),'binding_correction':a.read(PREV/'others/binding_correction_refs.json')}
    a.save(HERE/'protocols/accounts.json',protocol)
    a.save(HERE/'others/protocol_refs.json',{p.relative_to(HERE).as_posix():a.material(EX,p).to_dict() for p in (HERE/'protocols/accounts.json',Path(__file__))})
    print('EX044_BOUNDARY_FROZEN',flush=True)
def run():
    for key,ref in a.read(HERE/'others/protocol_refs.json').items():assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(HERE/key).read_bytes()
    for key,ref in a.read(PREV/'others/binding_correction_refs.json').items():assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(PREV/key).read_bytes()
    a.request=corrected.request;a.run(HERE.name,False)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
