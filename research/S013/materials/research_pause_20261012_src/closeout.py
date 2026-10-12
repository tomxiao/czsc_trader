"""User-authorized S013 research pause closeout; no strategy/evaluator calls."""
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-pause-20261012'
MATERIALS=ROOT/'research/S013/materials'
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_confirm_execution as base  # noqa: E402
from strategy_evaluator import AssessmentEvidence
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

DECISION='S013的候选在年化收益、最大回撤、交易频率、稳健性方面都稍显逊色。在没找到新的数据源以及研究方法之前，我决定暂停研究。请完成收尾工作。'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    out=importlib.util.module_from_spec(spec)
    sys.modules[name]=out
    spec.loader.exec_module(out)
    return out

def report_pair(proof_path):
    proof=base.read(proof_path)
    formal=ROOT/(proof.get('formal_report') or proof.get('formal'))
    copy=ROOT/(proof.get('experiment_report') or proof.get('copy'))
    assert proof['status']=='PASS' and formal.read_bytes()==copy.read_bytes()
    assert base.digest(formal)==proof['formal_sha256']
    assert base.digest(copy)==(proof.get('copy_sha256') or proof['formal_sha256'])
    return {'formal':formal.relative_to(ROOT).as_posix(),'copy':copy.relative_to(ROOT).as_posix(),
        'sha256':base.digest(copy),'bytes':copy.stat().st_size,'status':'EXACT'}

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    review=base.read(ROOT/'research/S013/reviews/20261012_new_four_203/results.json')
    freq=base.read(ROOT/'research/S013/reviews/20261012_frequency_117/review.json')
    registry=sorted((ROOT/'research/registrations/S013/candidates').glob('*.json'))
    assert len(registry)==review['candidate_count']==203 and review['qualified_count']==0
    assert freq['candidate_count']==117 and freq['distinct_economic_paths']==58
    expected={r['candidate_id'] for r in review['rows']}
    assert expected=={p.stem for p in registry}
    immutable_files=[p for root in ('research/registrations/S013','research/S013/experiments',
        'research/S013/reviews','research/S013/deliveries') for p in (ROOT/root).rglob('*') if p.is_file()]
    prior_manifest={p.relative_to(ROOT).as_posix():base.digest(p) for p in immutable_files}
    protected={p:base.digest(ROOT/p) for p in ('docs/DEV_AGENT.md','research/RSCH_AGENT.md')}
    rounds=[]
    for number in range(89,99):
        exp=ROOT/f'research/S013/experiments/EX{number:03d}_20261012'
        budget=base.read(exp/'protocols/budget_receipt.json')
        validation=base.read(exp/'protocols/delivery_validation.json')
        assert validation['status']=='PASS' and validation['scope']=='FULL'
        assert budget['completed']==number-88 and budget['remaining']==98-number
        assert budget['pause_after_EX098'] and not budget['objective_achieved']
        pair=report_pair(exp/'protocols/report_copy_verification.json')
        if (exp/'protocols/report_copy_verification_v2.json').exists():
            amended=base.read(exp/'protocols/report_correction_v2.json')
            assert amended['validation']['status']=='PASS'
            pair=report_pair(exp/'protocols/report_copy_verification_v2.json')
        rounds.append({'experiment':exp.name,'completed':number-88,'remaining':98-number,
            'FULL':'PASS','new_accounts':budget['new_accounts_this_round'],'final_report':pair})
    assert not (ROOT/'research/S013/experiments/EX099_20261012').exists()
    recent=[report_pair(ROOT/p) for p in ('research/S013/reviews/20261012_new_four_203/report_copy_verification.json',
        'research/S013/reviews/20261012_frequency_117/report_copy_verification.json')]
    old=base.read(ROOT/'research/S013/reviews/20261012_existing_candidates/review.json')
    parent=next(r for r in old['rows'] if r['candidate_id']=='C8880')
    econ=load('pause_readonly_economics',ROOT/'research/S013/experiments/EX074_20261011/src/economics_reference.py')
    gates=load('pause_readonly_gates',ROOT/'.tmp/s013-new-goal/gates_v2.py')
    points=[]
    for r in parent['standard32_sources']:
        ref=r['reference']
        path=ref_path=EvidenceRef.from_dict(ref).resolve(ROOT)
        assert base.digest(path)==ref['sha256']
        data=base.read(ref_path)
        fact=econ.economics(AssessmentEvidence.from_dict(data['assessment_evidence'][0]))
        evaluated=gates.from_economics(fact)
        points.append({'index':r['index'],'source':ref,'gates_v2':{**asdict(evaluated),'qualified':evaluated.qualified},
            'net_cagr':fact['net_cagr'],'full_drawdown':fact['full_drawdown']})
    counts={key:sum(r['gates_v2']['gates'][key] for r in points) for key in points[0]['gates_v2']['gates']}
    assert len(points)==32 and counts=={'return':7,'annual_drawdown':32,'positive_buyhold_year_frequency':5,'negative_buyhold_year_profit':2}
    sensitivity={'candidate':'C8880','method':'13 coordinates; normalized totalL2 .05;32PCG64seed13;integerHALF_EVEN;quantileLINEAR',
        'centre_cagr':parent['centre_net_cagr'],'centre_full_drawdown':parent['centre_drawdown'],
        'cagr_q10':parent['five_checks']['parameter_absolute_q10_cagr'],
        'drawdown_q90':parent['five_checks']['parameter_absolute_q90_drawdown'],
        'new_four_point_counts':counts,'new_four_joint_pass':sum(r['gates_v2']['qualified'] for r in points),
        'old_all_period_frequency_pass_count_diagnostic_only':parent['standard32_gate_counts']['frequency'],
        'points':points,'new_accounts':0,'new_parameters':0,'old_results_changed':False}
    base.write(MATERIALS/'c8880_new_four_parameter_review_20261012.json',sensitivity)
    state={'kind':'USER_RESEARCH_PAUSE_DECISION','batch':'S013','state':'PAUSED','recorded_on':'2026-10-12','timezone':'Asia/Shanghai',
        'authority':'current direct human message','human_message':DECISION,'research_objective_achieved':False,
        'last_experiment':'EX098_20261012','registered_candidates':203,'centre_new_four_pass':0,
        'last_authorized_quota':{'EX089_to_EX098':10,'completed':10,'remaining':0,'EX099_authorized':False},
        'current_action':'complete pause records and preserve existing evidence',
        'prior_autonomous_research_authorization':'suspended by latest user decision; not permission to resume',
        'resume':'new data-source/research-method proposal and inspectable incremental rationale; user decides whether and how to resume, including budget',
        'new_information_does_not_automatically_resume':True,'candidate_eligibility_unchanged':True,
        'candidate_retirement_or_PTE_selection':False,'production_changes':False,
        'preservation':'retain historical accounts/registrations/immutable reports/local assets and needed caches; no deletion or overwrite',
        'git':'retain codex/s013-mechanism-robustness; local closeout commit; merge/tag/push require separate authorization'}
    base.write(MATERIALS/'research_pause_20261012.json',state)
    integrity={'status':'PASS','date':'2026-10-12','scope':'latest ten rounds and two centre/read-only review report references; immutable local research preservation',
        'experiment_directory_count':len(list((ROOT/'research/S013/experiments').glob('EX???_????????'))),
        'rounds':rounds,'recent_reviews':recent,'registered_candidates':203,
        'existing_research_files_before':prior_manifest,'protected_user_document_sha256':protected,
        'git_before':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'runtime_check':{'named_S013_python_processes':0,'related_automation_config_matches':0,'collaborators':'all completed',
             'basis':'root read-only process/automation scan and collaboration snapshot before closeout; unrelated services untouched'},
        'assets_backup_claim':'local evidence preserved; Git alone excludes ignored assets, no remote/complete-machine backup claimed',
        'new_experiments':0,'new_accounts':0,'new_fits':0}
    for relative,expected_hash in prior_manifest.items():
        assert base.digest(ROOT/relative)==expected_hash
    for relative,expected_hash in protected.items():
        assert base.digest(ROOT/relative)==expected_hash
    base.write(MATERIALS/'research_pause_provenance_20261012.json',integrity)
    ctx=base.common().context(1)
    exp=ExperimentRef('S013','EX098_20261012')
    source_dir=MATERIALS/'research_pause_20261012_src'
    source_dir.mkdir(exist_ok=False)
    with (source_dir/'closeout.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    paths=[MATERIALS/'research_pause_20261012.json',MATERIALS/'research_pause_provenance_20261012.json',
        MATERIALS/'c8880_new_four_parameter_review_20261012.json',source_dir/'closeout.py',
        ROOT/'research/S013/reviews/20261012_new_four_203/summary.json',
        ROOT/'research/S013/reviews/20261012_frequency_117/review.json']
    refs={p.relative_to(ROOT).as_posix():base.put(ctx,exp,p) for p in paths}
    report='''# S013：用户决定暂停研究及收尾（2026-10-12）

研究状态为PAUSED，研究目标尚未达成。用户认为现有候选在年化收益、最大回撤、交易频率和稳健性方面不足，决定在没有新的数据来源与研究方法之前暂停。收尾资料完成不表示策略验收通过。

用户原话：S013的候选在年化收益、最大回撤、交易频率、稳健性方面都稍显逊色。在没找到新的数据源以及研究方法之前，我决定暂停研究。请完成收尾工作。

## 截止结果及关键资料

- 研究推进至EX098，共98个实验目录；并非98套均按新四门和32点完成验收的策略。最后授权EX089–EX098完成10/10，剩余0，EX099没有授权。
- 203个正式登记候选，按原策略实际账本和统一固定1%buyhold基准检查中心，新四门联合通过0；收益147、年度回撤195、盈利年份频率8、下跌年份盈利134分别通过。182个原策略溢价为1%，另21个保留原溢价，未规范改参重跑。195份旧schema5证据未冒充当前schema6；登记资格不更改。
- 117个仅缺盈利年份频率的候选，在这段历史有58条不同交易路径。最近六个均72笔、差5笔，实际同一路径且无买入确认；收益余量约0.165个百分点。规则挡过赢家，也挡过输家，尚无在T日可识别并保留其余三门的新增有效交易证据。事后盈利价格片段不是可执行机会或可追回利润。
- C8880中心净年化17.13%、全期回撤13.62%、盈利年份68笔不足77；13参数总距离5%的32点，收益Q10 6.40%、回撤Q90 28.35%。新四门逐项通过7/32、32/32、5/32、2/32，联合0/32。旧全期频率27/32不能充当新盈利年份频率5/32。
- EX089–EX092为组件检验，0新完整账户；EX093–EX098各1个完整中心，均未过新四门，按事前规则停止新32和双费评价。没有这些新策略的扰动Q10/Q90，不能填0或继承C8880扰动。

主要报告：[EX098额度收口](research/S013/experiments/EX098_20261012/others/report.md)、[203中心检查](research/S013/reviews/20261012_new_four_203/report.md)、[203明细](research/S013/reviews/20261012_new_four_203/centres.csv)、[117频率缺口](research/S013/reviews/20261012_frequency_117/report.md)、[117排名](research/S013/reviews/20261012_frequency_117/ranking117.csv)。EX096及EX097最终阅读采用[EX096修订报告](research/S013/experiments/EX096_20261012/others/report_v2.md)、[EX097修订报告](research/S013/experiments/EX097_20261012/others/report_v2.md)，原件保留。

## 已完成的收尾与保存边界

最新十轮正式FULL记录、报告副本及修订关系逐一核对，两个只读审查报告与正式报告逐字节一致。已核对203登记数量；暂停前S013命名计算进程及相关自动任务配置匹配均为0，协作任务已结束。仅补录暂停决定、收尾资料和已有C8880新门统计；0新实验/账户/模型，不新增机制、数据或优化。

历史实验、候选登记、价格和账户证据保持不可变；不删除assets或必要缓存。Git保存源码、报告和引用，不能替代被忽略的本地assets；本次保留本地资料，不声称已完成远端或完整环境备份。现有用户修改的DEV与RSCH文档保持原样，仅更新S013可变HANDOFF为最新暂停状态。

保留研究分支codex/s013-mechanism-robustness，本地保存收尾；没有合并master、打tag或推送。没有选型、冻结、PTE或生产变更。旧资格按旧依据解释，不把本次暂停等同候选注销。

## 恢复条件与下一步

此前自主研究授权按本次用户决定暂停。发现线索不自动恢复；下次先提出新的数据源/研究方法、适用权限和具体增量，明确机制、最强反证、最小验证方案及预算，由用户决定是否恢复。不得以改名、邻窗或调阈值冒充新方法，不沿用已用完的十轮额度。

下一步是保持暂停，等待用户的新方向及明确授权。当前没有待运行实验、待补账户或自动继续计划；目标未达成不因收尾变为完成。

## 正式关联证据（项目根目录相对路径）

'''
    report+=''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    evidence=tuple(EvidenceRef.from_dict(ref) for ref in refs.values())
    summary=m.SearchSummary('S013-user-pause-closeout-20261012','用户决定暂停后的收尾和已有关联证据核对',
        '0新评价/配置；仅保存暂停决定、最新报告完整性和已有统计；目标尚未达成',0,0,
        '研究暂停，资料收尾完成，未来恢复须由用户决定',
        ('COMPLETE仅表示收尾交付完成，不是研究目标达成','保留旧合同/资格及本地资产，不声称远端备份'),evidence)
    revision=max(int(p.name) for p in (ROOT/'research/S013/deliveries/CANDIDATES').iterdir() if p.name.isdigit())+1
    predecessor=m.DeliveryReference.from_dict(base.read(ROOT/'research/S013/assets/deliveries/MANDATE/7/receipt.json')['reference'])
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.CANDIDATES,revision,(predecessor,)),
        m.DeliveryContent(m.CandidateSet((),(),(summary,),'用户决定暂停；无新合格候选；收尾完成不等于策略通过'),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS'
    base.write(MATERIALS/'research_pause_reference_20261012.json',receipt.reference.to_dict())
    base.write(MATERIALS/'research_pause_validation_20261012.json',validation.to_dict())
    base.write(MATERIALS/'research_pause_evidence_20261012.json',refs)
    formal=ROOT/f'research/S013/deliveries/CANDIDATES/{revision}/report.md'
    copy=MATERIALS/'research_pause_20261012.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert copy.read_bytes()==formal.read_bytes()
    base.write(MATERIALS/'research_pause_report_copy_20261012.json',{'status':'PASS','formal':formal.relative_to(ROOT).as_posix(),
        'copy':copy.relative_to(ROOT).as_posix(),'formal_sha256':base.digest(formal),'copy_sha256':base.digest(copy),
        'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,'exact_bytes':True})
    for relative,expected_hash in prior_manifest.items():
        assert base.digest(ROOT/relative)==expected_hash
    for relative,expected_hash in protected.items():
        assert base.digest(ROOT/relative)==expected_hash
    print({'research_status':'PAUSED','objective_achieved':False,'closeout':'COMPLETE','CANDIDATES':revision,
        'FULL':'PASS','report_copy':'EXACT','immutable_existing_files':len(prior_manifest),'new_experiments':0,'new_accounts':0},flush=True)

if __name__=='__main__':
    main()
