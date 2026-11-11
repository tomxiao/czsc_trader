"""Inspect, then explicitly open the approved three-candidate S019 stage-four scope."""
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext,create_research_context,create_experiment,ExperimentRequest,
    get_research_overview,load_candidate,publish_evidence,record_research_decision,
    update_research_intent,ResearchIntentUpdate,validate_delivery)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey,CandidateEvidence
from strategy_manager import freeze_contracts as f

import run_accounts as runner

ROOT = runner.ROOT
BATCH = ROOT/'research/S019'
WORK = BATCH/'experiments/EX050_20261111'
PREVIOUS = BATCH/'experiments/EX049_20261111'


def read(path):
    return json.loads(path.read_bytes())


def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorization-file',type=Path,required=True,
        help='Actual user approval text prepared by the root agent; copied unchanged into this experiment')
    parser.add_argument('--workers',type=int,default=61)
    parser.add_argument('--open',action='store_true')
    args = parser.parse_args()
    assert not WORK.exists(), 'Inspect the existing experiment instead of creating another'
    authorization_path = args.authorization_file.resolve()
    assert authorization_path.is_relative_to(ROOT) and authorization_path.is_file()
    authorization = authorization_path.read_bytes()
    assert authorization.decode('utf-8').strip()
    assert args.workers == 61, 'Approved maximum Windows process-pool concurrency is 61'
    resources = {'workers':61,'native_threads':1,'batch_size':61,'random_seed':19,
        'logical_cpu_count_observed':os.cpu_count(),'pool_limit_basis':'Root verified Windows ProcessPoolExecutor maximum 61'}
    runner.core.ExecutionResources(61,1,19)
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['stage'] == 'STAGE_THREE' and intent['continuous_stage3_status'] == 'COMPLETE'
    assert not intent.get('active_experiment')
    budget = intent['continuous_stage3_budget']
    assert budget['used_rounds'] == 3 and budget['remaining_rounds'] == 7
    receipt_path = BATCH/'deliveries/CANDIDATES/7/receipt.json'
    predecessor = d.DeliveryReference.from_dict(read(receipt_path)['reference'])
    assert predecessor.to_dict() == intent['continuous_stage3_delivery']
    validation = validate_delivery(repo,predecessor,scope=d.DeliveryValidationScope.INTEGRITY)
    assert validation.status is d.ValidationStatus.PASS
    prior = read(PREVIOUS/'others/results.json')
    assert prior['status'] == 'COMPLETE' and prior['replay_statistics_complete']
    assert read(PREVIOUS/'others/publication.json')['validation']['status'] == 'PASS'
    selected = list(runner.IDS)
    qualified = intent['continuous_stage3_qualified_candidates']
    assert set(selected) <= set(qualified)
    centers = []
    for cid in selected:
        candidate = load_candidate(repo,CandidateKey('S019',cid))
        standard = prior['accounts'][cid]
        pressure = prior['pressure_accounts'][cid]
        assert standard['candidate']['eligible'] and all(standard['candidate']['gates'].values())
        assert standard['definition'] == runner.normalize(candidate.definition.to_dict()) == pressure['definition']
        assert standard['content_hash'] == pressure['content_hash'] == candidate.content_identity.content_sha256
        assert candidate.definition.source_sha256 == runner.SOURCE_HASH
        assert (candidate.source_root/'strategy.py').read_bytes() == runner.SOURCE.read_bytes()
        runner.authenticate_header(standard['account_ref'],candidate,False)
        runner.authenticate_header(pressure['account_ref'],candidate,True)
        design,_,_ = runner.construction(candidate)
        assert design.point_count == runner.POINT_COUNTS[cid]
        centers.append({'id':cid,'definition':standard['definition'],'content_hash':standard['content_hash'],
            'account_ref':standard['account_ref'],'center_account':standard['account_ref'],'stress_account':pressure['account_ref'],
            'candidate':standard['candidate'],'pressure_candidate':pressure['candidate'],
            'pressure_gates':pressure['pressure_gates'],'pressure_eligible':pressure['pressure_eligible'],
            'source_account_path':(PREVIOUS/f'others/{cid}_account.json').relative_to(ROOT).as_posix(),
            'source_stress_account_path':(PREVIOUS/f'others/{cid}_stress_account.json').relative_to(ROOT).as_posix(),
            'source_experiment':prior['manifest']['experiment']})
    used = runner.used_ids()
    first = max(int(cid[1:]) for cid in used)+1
    assert first+1698 <= 10000
    print('SETUP_READY','EX050_20261111',runner.POINT_COUNTS,'new IDs',f'C{first:04}',f'C{first+1697:04}',
        '61 workers/native1; optimization budget remains 3/10; no accounts executed',flush=True)
    if not args.open:
        return
    assert (Path(__file__).parent/'run_accounts.py').is_file()
    ctx = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    exp = create_experiment(ctx,ExperimentRequest('C0966、C1010、C0909完整阶段四稳健性自检',
        '按批准三候选范围完整检验参数邻域、费用、时间、集中性与统计不确定性，保留原目标并比较NAR。',date(2026,11,11)))
    assert exp.resolve(ROOT) == WORK
    for name in ('setup.py','run_accounts.py'):
        (WORK/'src'/name).write_bytes((Path(__file__).parent/name).read_bytes())
    (WORK/'src/strategy.py').write_bytes(runner.SOURCE.read_bytes())
    (WORK/'protocols/authorization.md').write_bytes(authorization)
    save(WORK/'others/opening_overview.json',get_research_overview(repo,batch).to_dict())
    save(WORK/'others/predecessor_validation.json',validation.to_dict())
    save(WORK/'protocols/centers.json',centers)
    approval = publish_evidence(ctx,d.MaterialEvidenceWrite(exp,'stage-four-three-center-authorization',authorization,'text/markdown','md'))
    decision = record_research_decision(repo,f.ResearchDecision('S019-STAGE4-CONTINUOUS-20261111','S019',f.DecisionAction.APPROVE,
        f.StageAdvanceSubject(CandidateEvidence(receipt_path.relative_to(ROOT).as_posix(),digest(receipt_path)),'ASSESSMENT'),
        CandidateEvidence(approval.resolve(ROOT).relative_to(ROOT).as_posix(),approval.sha256),
        '用户批准C0966、C1010、C0909完整阶段四，采用接口允许的最大账户并发；原目标和剩余7轮优化额度保持。'))
    save(WORK/'others/authorization.json',{'evidence':approval.to_dict(),'decision':decision.to_dict()})
    mandate = read(BATCH/'deliveries/MANDATE/2/receipt.json')['reference']
    save(WORK/'protocols/scope.json',{'selected':selected,'deferred':[cid for cid in qualified if cid not in selected],
        'predecessor':predecessor.to_dict(),'source_mandate':mandate,'expected_parameter_counts':runner.POINT_COUNTS,
        'first_child':first,'resources':resources,'approval_decision':decision.to_dict(),
        'complete_original_set_retained':True,'optimization_rounds_debited':0,'optimization_budget_snapshot':budget,
        'reuse':'Three original standard accounts and three original pressure accounts; exact same source/parameters/input/execution.'})
    plan = f'''# 三候选完整阶段四执行方案

本轮执行用户已批准的C0966、C1010、C0909范围，承接CANDIDATES/7与MANDATE/2。所有指标、样本及排序沿用原协议；其余达标配置保留未检。

## 参数邻域与身份

C0966的有效连续轴为weak_fraction、quiet_fraction、participation_threshold、participation_width、trail_atr；hard退出的exit_width固定。C1010和C0909再加入有效exit_width，共六轴。全部有效连续轴采用相对中心±5%及中心三水平完整笛卡尔点集，排除中心后分别242、728、728点，共1698点。整数参数最小合法变化超过5%时固定，类别与布尔为原结构。

通过公开build_parameter_neighborhood_design生成合法点集，再由ParameterEvaluationPlan、CandidateDerivation与EvaluationLineage绑定精确父候选、完整参数、计划及账户请求。保留全部N个等权点，技术失败或缺失保留在分母。新增子ID预留C{first:04}至C{first+1697:04}，正式预检再次扫描历史提议、预留与登记冲突。

中心NAR≥55%、Calmar≥5、MDD≤25%且≤同费用买持80%，滚动60日闭合中位数≥6、至少3笔覆盖≥90%。邻点联合要求NAR≥50%、Calmar≥4.5、MDD≤同费用买持90%，通过比例≥80%，全部邻点MDD≤25%。邻点频率保留诊断，中心频率要求适用于中心。费用压力每侧0.2%，NAR≥50%、Calmar≥4.5、MDD≤25%且小于同费用买持；买持回撤为0时要求同为0。

## 样本、费用与复用

2021预热，2022-01-03至2026-10-30连续已见历史；MU/SOXX、HFQ整数单位、10万美元、标准每侧0.1%、原限价买入/市价卖出执行合同保持。标准中心与0.2%费用压力共6份精确证据沿用EX049所绑定的原账户。先准备当前请求，再逐字段核验仅experiment归属变化，保留旧证据身份及原请求哈希。邻点的新父计划及子ID均单独绑定，历史相同参数不会被改签。

## 资源、恢复与工作量

根会话已核查Windows ProcessPoolExecutor最大账户并发为61，本轮冻结61进程、每进程1原生线程、每批最多61账户。使用同一公共TDR执行会话、共享输入与一份标准费用买持；压力买持随旧压力证据复用。预计新增1698策略账户、1标准买持，复用6策略场景，共1704策略场景。运行中保留不可变逐账户引用、逐账户结果及每批统计；恢复使用显式--recover和公共CREATE/RESUME检查点，核对源码、请求与已有证据身份，异常逐项保留并显式处理。

阶段四参数、时间、集中性、执行/费用和统计五项核验完成后发布ASSESSMENT/3。阶段三新额度已用3/10、剩余7，本轮自检扣减优化轮0；阶段五选型、冻结及生产另行批准。逐账户回放、聚合及发布分别报告实际耗时。
'''
    (WORK/'protocols/plan.md').write_bytes(plan.encode())
    (WORK/'report.md').write_bytes('# S019三候选完整阶段四\n\nStatus: IN_PROGRESS\n\n完整1698邻点与六份精确中心/压力证据，原目标保持。\n'.encode())
    fresh = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert fresh == intent
    fresh.update(stage='STAGE_FOUR',continuous_stage3_next_stage_approval='APPROVED_THREE_CANDIDATES',
        stage_four_continuous_approval=decision.to_dict(),stage_four_continuous_candidates=selected,
        stage_four_continuous_deferred_candidates=[cid for cid in qualified if cid not in selected],
        stage_four_continuous_status='IN_PROGRESS',active_experiment=exp.to_dict(),
        next_action='以61账户进程完整完成C0966/C1010/C0909阶段四自检，全部原目标保持；阶段三剩余7轮额度保留。')
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=fresh),actor='RSCH',
        reason='用户批准三个指定候选完整阶段四及最大账户并发；本轮使用固定验收点集，扣减优化轮0。')
    assert read(ROOT/'research/registrations/S019/family.json')['research_intent']['continuous_stage3_budget'] == budget
    print('EX050_CREATED',selected,'61 workers/native1; budget unchanged',flush=True)


if __name__ == '__main__':
    main()
