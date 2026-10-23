"""Complete the observed permission-exit domain using its finite-state bound."""
import argparse
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent
PREV=BASE/'EX042_20261023';EXIT_SOURCE=BASE/'EX045_20261023'
sys.path.insert(0,str(PREV/'src'))
import accounts as a
import run_accounts as corrected

EX=a.ExperimentRef('S015',HERE.name)
SOURCE_KEY='src/strategy_runtime/strategies/price_information.py'
MAX_RUNS={'A/path':16,'A/risk':18,'A/and':8,'B/path':22,'B/risk':24,'B/and':13}
OLD_EXPERIMENTS=tuple(f'EX{i:03d}_20261023' for i in range(42,47))


def key(p):return p['family'],p['mode'],p.get('exit_rule','fixed'),p['hold']


def configurations():
    result=[]
    for family,mode,start,stop in [('A','path',10,16),('A','risk',10,18),('B','path',10,22),('B','risk',10,24),('B','and',10,13)]:
        for hold in range(start,stop+1):
            if family=='B' and mode=='path' and hold==15:continue
            result.append({'family':family,'mode':mode,'hold':hold,'exposure':1.,'exit_rule':'permission'})
    assert len(result)==47 and len({key(p) for p in result})==47
    return result


def authenticate_dependencies():
    a.authenticate()
    refs=a.read(EXIT_SOURCE/'others/protocol_refs.json')
    for name,r in refs.items():assert a.EvidenceRef.from_dict(r).resolve(a.ROOT).read_bytes()==(EXIT_SOURCE/name).read_bytes()
    for name,r in a.read(PREV/'others/binding_correction_refs.json').items():
        assert a.EvidenceRef.from_dict(r).resolve(a.ROOT).read_bytes()==(PREV/name).read_bytes()
    return refs


def prior_domain(require_results=True):
    rows=[]
    for name in OLD_EXPERIMENTS:
        result_path=BASE/name/'others/results.json'
        if result_path.exists():
            data=a.read(result_path)
            for row in data['rows']:rows.append({'experiment':name,'candidate_id':row['candidate_id'],'key':key(row['parameters']),'basis':'completed_result'})
        else:
            raise RuntimeError(f'{name} must have complete others/results.json before EX047 preparation')
    assert len(rows)==112 and len({tuple(r['key']) for r in rows})==112
    return rows


def verify_domain(require_results=True):
    prior=prior_domain(require_results);previous={tuple(r['key']) for r in prior};new={key(p) for p in configurations()}
    fixed={(f,m,'fixed',h) for f in ('A','B') for m in ('path','risk','and') for h in range(1,10)}
    permission={(fm.split('/')[0],fm.split('/')[1],'permission',h) for fm,maximum in MAX_RUNS.items() for h in range(1,maximum+1)}
    redundant={('A','and','permission',9),('B','path','permission',30),('B','and','permission',15),('B','and','permission',30)}
    assert len(fixed)==54 and len(permission)==101
    assert not previous & new
    assert previous|new==fixed|permission|redundant
    assert len(previous|new)==159
    return prior


def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    # Intentionally no assertion about qualified_centers: a prior success does
    # not invalidate this predeclared, finite completion of the same domain.
    controls=verify_domain(require_results=True);source_refs=authenticate_dependencies()
    checks=a.read(HERE/'others/runtime_checks.json');assert checks['status']=='PASS'
    assert checks['maximum_permission_runs']==MAX_RUNS
    assert checks['permission_runtime_sha256']==a.EvidenceRef.from_dict(source_refs[SOURCE_KEY]).sha256
    protocol={
      'authorization':'用户已批准阶段三自主研究和不限实验预算。本轮仅补全同一模型、许可和执行合同在已见开发池内尚有可能不同的持有上限表达，不新增模型/阈值/数据。',
      'question':'EX046的1..9和选择性15/30仍有许可退出整数空档；利用已知许可序列的最长连续真段，为本开发池推导可验证的有限持有域，补齐其余47配置。',
      'selection_history':'EX042-46均属同一已反复观察开发池；A/B模型及path/risk/and模式和先前持有边界都已有开发选择。最长连续许可段是在整个已见434日上事后计算的研究搜索边界，不是当时可知的未来持续期，更不是独立验证或未来上界。冻结前引用既有结果，但不因其中心通过数量而改变本轮47个配置。',
      'configurations':configurations(),'maximum_permission_runs':MAX_RUNS,
      'finite_state_proof':'许可序列只由固定市场输入和既有模型/阈值决定，与hold无关。规范起点为空仓意图，任何false日令active年龄归0，idle也不进入。每个连续true段从年龄1开始，长度至多M；当hold>=M时，该段内不会因age>=hold提前退出，因为第M个true日开始时年龄至多M-1。随后false日各hold都退出；若true段在样本末端截断，至样本末端各hold仍相同。逐段归纳，所有hold>=M在本固定序列435规范行的目标、年龄、预测、许可均与hold=M完全一致。',
      'checks':'用认证EX036的13特征、EX042 A/B系数及EX045冻结运行时重新计算六个许可序列，确认M=16/18/8/22/24/13；每组比较hold=M、M+1、434全部435行，再核对四个既测高上限冗余身份与各自M。独立标量状态机核验年龄和target，不运行账户。',
      'new_domain':'A-path10..16共7；A-risk10..18共9；B-path10..22排除已测15共12；B-risk10..24共15；B-and10..13共4；A-and无需新增。合计47新配置94账户。',
      'domain_counts':{'new_configurations':47,'new_account_scenarios':94,'reused_parameter_identities':112,'combined_parameter_identities':159,'fixed_representatives':54,'permission_representatives':101,'finite_domain_representatives':155,'previously_tested_above_bound_redundant_identities':4,'technical_duplicate_scenarios':0},
      'count_interpretation':'155是54个fixed持有参数加101个permission有限域代表表达，不主张155个独立信息或不同交易行为。159是实际跨实验参数身份，含A-and permission9、B-path permission30、B-and permission15/30四个已测高于本样本M的冗余身份；有限域内部也可能出现额外相同行为，另行报告。',
      'fixed_boundary':'固定持有1..9已有54配置；当前固定单周期且无提前退出的hold>=10受EX044原频率必要条件排除。该代数频率结论不用于permission；许可域上界来自本样本状态机等价证明。',
      'scope_limit':'许可hold>=M等价结论只适用于固定434日市场输入、既有预测时间表及同一规范起点。不能推广到未来行情、其他窗口、新训练模型、不同许可阈值、初始持仓或交易规则。两评价窗口使用共同canonical历史，同输出不会改变本合同下的订单意图；经济等价仍以实际账户复用与账本核验为证。',
      'runtime':'使用EX045源及fixed/permission参数契约，本轮全部permission。EX042原13特征、模型、训练时钟、风险阈值、全仓、费用、限价单、次日执行、二窗口独立十万元均不变。',
      'execution':'公共TDR、Optuna固定排队、4进程/原生线程1/seed13；认证EX042修正request并把SOURCE设为EX045。已完成相同源的串并行及五账本复验，本轮不重复技术账户。',
      'interpretation':'保留全部结果和既有成功/失败事实，不预设联合中心必然为0。有限域完成只封闭这一模型和许可机制的当前持有表达，不能证明所有价格行为策略不可能达标；若仍不合格，下一研究决定需基于未解决机制与新证据，不能靠继续增大等价hold制造新实验。',
      'controls_index':controls,
      'controls_results':[a.material(a.ExperimentRef('S015',name),BASE/name/'others/results.json').to_dict() for name in OLD_EXPERIMENTS],
      'fixed_frequency_bound':a.material(a.ExperimentRef('S015','EX044_20261023'),BASE/'EX044_20261023/others/frequency_bound.json').to_dict(),
      'source_experiment':'EX045_20261023','source_ref':source_refs[SOURCE_KEY],'runtime_source_validation':source_refs,
      'dependencies':a.read(PREV/'others/account_refs.json'),'binding_correction':a.read(PREV/'others/binding_correction_refs.json')}
    a.save(HERE/'protocols/accounts.json',protocol)
    paths=[Path(__file__),HERE/'src/check_boundary.py',HERE/'others/runtime_checks.json',HERE/'protocols/accounts.json']
    a.save(HERE/'others/protocol_refs.json',{p.relative_to(HERE).as_posix():a.material(EX,p).to_dict() for p in paths})
    print('EX047_FINITE_PERMISSION_DOMAIN_FROZEN',flush=True)


def run():
    for name,ref in a.read(HERE/'others/protocol_refs.json').items():
        assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(HERE/name).read_bytes()
    refs=authenticate_dependencies();verify_domain(require_results=True)
    protocol=a.read(HERE/'protocols/accounts.json')
    assert protocol['configurations']==configurations() and protocol['source_ref']==refs[SOURCE_KEY]
    for ref in protocol['controls_results']:
        r=a.EvidenceRef.from_dict(ref)
        assert r.resolve(a.ROOT).read_bytes()==(BASE/r.experiment.experiment_id/'others/results.json').read_bytes()
    assert a.EvidenceRef.from_dict(protocol['fixed_frequency_bound']).resolve(a.ROOT).read_bytes()==(BASE/'EX044_20261023/others/frequency_bound.json').read_bytes()
    a.SOURCE=EXIT_SOURCE/'src/strategy_runtime';a.request=corrected.request;a.run(HERE.name,False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);globals()[p.parse_args().mode]()
