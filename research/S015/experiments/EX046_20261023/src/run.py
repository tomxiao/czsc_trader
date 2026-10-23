"""Frozen finite holding-domain completion and selected permission boundaries."""
import argparse
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
BASE=HERE.parent
PREV=BASE/'EX042_20261023'
EXIT_SOURCE=BASE/'EX045_20261023'
sys.path.insert(0,str(PREV/'src'))
import accounts as a
import run_accounts as corrected

EX=a.ExperimentRef('S015',HERE.name)
SOURCE_KEY='src/strategy_runtime/strategies/price_information.py'


def configurations():
    fixed=[{'family':family,'mode':mode,'hold':hold,'exposure':1.,'exit_rule':'fixed'}
      for family in ('A','B') for mode in ('path','risk','and') for hold in (4,6,8)]
    fixed += [{'family':'B','mode':mode,'hold':9,'exposure':1.,'exit_rule':'fixed'} for mode in ('path','risk','and')]
    permission=[{'family':family,'mode':mode,'hold':hold,'exposure':1.,'exit_rule':'permission'}
      for family in ('A','B') for mode in ('path','risk','and') for hold in (1,2,4,5,6,8,9)]
    permission += [{'family':'B','mode':mode,'hold':hold,'exposure':1.,'exit_rule':'permission'}
      for mode in ('path','and') for hold in (15,30)]
    configs=fixed+permission
    assert len(fixed)==21 and len(permission)==46 and len(configs)==67
    assert len({configuration_key(p) for p in configs})==67
    return configs


def configuration_key(p):
    return p['family'],p['mode'],p.get('exit_rule','fixed'),p['hold']


def authenticate_dependencies():
    a.authenticate()
    refs=a.read(EXIT_SOURCE/'others/protocol_refs.json')
    for key,ref in refs.items():
        assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(EXIT_SOURCE/key).read_bytes()
    for key,ref in a.read(PREV/'others/binding_correction_refs.json').items():
        assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(PREV/key).read_bytes()
    return refs


def prior_domain():
    rows=[]
    for name in ('EX042_20261023','EX043_20261023','EX044_20261023','EX045_20261023'):
        data=a.read(BASE/name/'others/results.json')
        assert data['qualified_centers']==0
        for row in data['rows']:
            rows.append({'experiment':name,'candidate_id':row['candidate_id'],'key':configuration_key(row['parameters'])})
    assert len(rows)==45 and len({tuple(row['key']) for row in rows})==45
    return rows


def verify_domain():
    controls=prior_domain();new=configurations();oldkeys={tuple(r['key']) for r in controls};newkeys={configuration_key(p) for p in new}
    assert not oldkeys & newkeys
    base_domain={(f,m,e,h) for f in ('A','B') for m in ('path','risk','and') for e in ('fixed','permission') for h in range(1,10)}
    extensions={('B',m,'permission',h) for m in ('path','and') for h in (15,30)}
    assert oldkeys|newkeys==base_domain|extensions
    return controls


def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    source_refs=authenticate_dependencies();controls=verify_domain()
    checks=a.read(HERE/'others/runtime_checks.json');assert checks['status']=='PASS'
    assert checks['fixed_equivalent_configs']==54
    assert checks['permission_runtime_sha256']==a.EvidenceRef.from_dict(source_refs[SOURCE_KEY]).sha256
    protocol={
      'authorization':'阶段三自主研究已授权，实验预算不限；本轮固定补全有限整数持有域并检验两条仍改善的许可退出边界。保持原模型、阈值、全仓、两窗口和经济目标。',
      'question':'此前固定3/1/2/5/7/部分9和许可3/7留下整数空档；固定补全同一模型六种家族模式在两种退出规则下1..9，比较完整账户，并只对B-path/B-and许可退出增加15/30上限。',
      'selection_history':'EX042-45共45配置中心联合通过数均为0，结果已见。固定A-path9较7部分改善，但净收益36.5382%、回撤30.1753%仍不满足中心。许可B-path上限3→7收益33.33%→59.23%、回撤19.30%→18.47%，B-and7较3也有收益改善，故预先选择两个B模式作15/30延伸。该选择是基于已见开发成绩的后继研究，不能称独立样本。',
      'configurations':configurations(),
      'domain_counts':{'new_fixed':21,'new_permission_1_to_9':42,'new_permission_long':4,'new_total':67,'reused':45,'integer_domain_total':108,'long_extension_total':4,'combined_distinct_total':112,'new_account_scenarios':134,'technical_duplicate_scenarios':0},
      'finite_domain':'固定退出新增六家族模式×hold4/6/8及B三个模式hold9；许可退出新增六家族模式×hold1/2/4/5/6/8/9；再加B-path/B-and×hold15/30。与42-45的45配置没有重复，合并恰为六家族模式×两退出×1..9共108及长边界4。',
      'runtime':'全部新配置使用EX045已冻结源。其fixed模式已扩展核对：A/B×path/risk/and×hold1..9共54配置在全部435规范行输出与EX042完全一致。permission active时年龄届满或当日许可失效退出，当日不重入；原NEXT_SESSION市场卖出不变。',
      'models':'完全复用EX042 frozen models_A/B及13个特征。禁止本轮重训、改变训练时钟、许可阈值或资金面输入；无入场、仓位、阈值和模型超参数搜索。',
      'execution':'SOURCE明确指向EX045运行时；使用EX042经修正的a.request，候选标识与实际reference_id一致；TDR公开入口、Optuna固定排队、4进程、原生线程1、seed13。EX042/45已有串并行及五账本技术复验，不重复账户前检。',
      'fixed_domain_boundary':'引用EX044独立代数频率上界：仅对当前固定持有、单意图周期、无提前退出的策略类，hold>=10不能满足滚动60日闭合数中位数>=6；hold10至多175/375个窗口可达6笔，中位数要求至少188个。故fixed整数1..9为本策略类未被这一必要条件排除的完整域。此为合同内交易频率可行性结论，不是模拟过所有更长账户，也不推广到permission提前退出。',
      'boundary_review':'许可退出15/30只是最大持有上限，可能提前退出，不能套用固定持有频率结论。如果长边界继续有有意义改善，结合实际频率、收益回撤归因与实现可行性再审核后继域；不按固定轮数自动停止，也不无限扩展没有证据的方向。',
      'reporting':'保留全部67新配置和45复用配置的结果、前沿改善及反证。双窗门槛、中心、频率、扰动和费用要求不改变；中心通过才考虑后续获准检验，不将局部改善宣称合格策略。',
      'controls_index':controls,
      'controls_results':[a.material(a.ExperimentRef('S015',name),BASE/name/'others/results.json').to_dict()
        for name in ('EX042_20261023','EX043_20261023','EX044_20261023','EX045_20261023')],
      'fixed_frequency_bound':a.material(a.ExperimentRef('S015','EX044_20261023'),BASE/'EX044_20261023/others/frequency_bound.json').to_dict(),
      'source_experiment':'EX045_20261023','source_ref':source_refs[SOURCE_KEY],
      'runtime_source_validation':source_refs,
      'dependencies':a.read(PREV/'others/account_refs.json'),
      'binding_correction':a.read(PREV/'others/binding_correction_refs.json'),
    }
    a.save(HERE/'protocols/accounts.json',protocol)
    paths=[Path(__file__),HERE/'src/check_runtime.py',HERE/'others/runtime_checks.json',HERE/'protocols/accounts.json']
    a.save(HERE/'others/protocol_refs.json',{p.relative_to(HERE).as_posix():a.material(EX,p).to_dict() for p in paths})
    print('EX046_67_CONFIGURATION_DOMAIN_FROZEN',flush=True)


def run():
    for key,ref in a.read(HERE/'others/protocol_refs.json').items():
        assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(HERE/key).read_bytes()
    refs=authenticate_dependencies();verify_domain()
    protocol=a.read(HERE/'protocols/accounts.json')
    assert protocol['configurations']==configurations()
    assert protocol['source_ref']==refs[SOURCE_KEY]
    for ref in protocol['controls_results']:
        r=a.EvidenceRef.from_dict(ref)
        assert r.resolve(a.ROOT).read_bytes()==(BASE/r.experiment.experiment_id/'others/results.json').read_bytes()
    assert a.EvidenceRef.from_dict(protocol['fixed_frequency_bound']).resolve(a.ROOT).read_bytes()==(BASE/'EX044_20261023/others/frequency_bound.json').read_bytes()
    a.SOURCE=EXIT_SOURCE/'src/strategy_runtime'
    a.request=corrected.request
    a.run(HERE.name,False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);globals()[p.parse_args().mode]()
