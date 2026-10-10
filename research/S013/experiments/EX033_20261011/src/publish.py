"""Immutable complete delivery of descriptive diagnosis, no new candidates/accounts."""
from diagnose import ROOT, SRC, RUNS, PROTO, EXPERIMENT, PRIOR, context, read, write, file_hash
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey
import subprocess
from importlib.metadata import version


def report_text(diagnosis, refresh):
    s, t = diagnosis['summary'], refresh['summary']
    counts = t['one_step_classes']
    divergent = sum(v for k,v in counts.items() if k != 'SAME_TARGET')
    assert divergent == sum(r['state_episodes']['target_different_days'] for r in diagnosis['points'])
    text = '''# S013：原策略退出与重新入场的连锁诊断

RSCH阶段三。用户已授权自主完成参数敏感性研究，无需逐轮评审。本轮只复用33个既有完整账户，新增账户、候选、参数搜索和生产变更均为0。总目标尚未达成；COMPLETE仅表示这份诊断交付完成。

## 为什么调整研究方向

C2132原中心满足四项经济要求，但原完整13维域、5%联合扰动32点的收益Q10仅5.8974%、回撤Q90达30.5044%。EX031/032波动时钟及半单位计数修正都未保住经济要求，停止继续调整时钟偏移。本轮检查退出日期是否通过重新入场和持仓年龄清零，放大后续路径差异，并保留“主要是入场规则直接差异”的竞争解释。

原生信号状态定义为空仓，或持仓路线与信号持仓年龄；原stop/trailing为null、cooldown为0、确认适用于所有入场，所以锚价、峰值、上次退出原因在此固定合同不影响未来目标动作。不同参数和滚动特征仍然存在，状态重同步不意味着以后交易相同，更不意味着现金/持仓数量相同。

最大连续不同状态段从共同前状态开始，到双方状态再次相同结束。双方目标仓位同为1仍可能路线/年龄不同；双方同日入场但路线不同也算状态分歧。逐日原规则重算精确复现原生状态、原因、目标与确认门判定，真实确认score和range特征来自原生账户，未宣称全特征从OHLC独立重建。

## 全部路径的观察结果

'''
    text += f"32个点共{s['episodes']}段状态分歧，{s['time_seeded_episodes']}段包含TIME起始原因（{s['time_seeded_episodes']/s['episodes']:.2%}）。平均每点状态不同{s['mean_state_different_days']:.4f}日，目标仓位不同{s['mean_target_different_days']:.4f}日；最长状态分歧{s['longest_state_episode']}个交易日。不同点共享数据与对照，这些不是独立统计样本，也不代表参数单独因果。\n\n"
    text += '|分歧起点的原策略→扰动点动作|段数|\n|---|---:|\n'
    for key,value in sorted(s['reason_pairs'].items(),key=lambda x:-x[1]):
        text += f'|{key}|{value}|\n'
    text += '\n|点序号|状态分歧段|最长段|段长中位数|TIME起点段|目标不同日|\n|---|---:|---:|---:|---:|---:|\n'
    for r in diagnosis['points']:
        e = r['state_episodes']
        text += f"|{r['point_index']}|{e['count']}|{e['duration_max']}|{e['duration_median']:g}|{e['time_seeded_episodes']}|{e['target_different_days']}|\n"
    text += '\n## 单步：当前规则与继承状态的区别\n\n'
    text += '每个真实时点检查p规则/特征与q规则/特征各自应用于双方已有状态，共四组合。两原组合须精确复现原生记录，另两组合只计算当日一步，不传播新的状态或账户。双方实际目标不同而固定双方任一状态换规则都不改变目标，称继承状态差异；固定任一规则换状态都不改变目标，称当前规则/特征差异；其余称混合。原参数与其滚动特征一起变化，不能称单个H的因果分解。SAME_TARGET也不等于SAME_STATE。\n\n'
    text += '|目标不同日的单步类别|全部32点日数|占目标不同日|\n|---|---:|---:|\n'
    for key in ('INHERITED_STATE_ONLY','CURRENT_FEATURE_RULE_ONLY','MIXED'):
        text += f'|{key}|{counts.get(key,0)}|{counts.get(key,0)/divergent:.2%}|\n'
    text += '\n## 持续入场机会与重新买回\n\n'
    c = t['center_refresh']
    text += f"原中心bear有{c['bear_time_exits']}次TIME退出，其中{c['unrefreshed_bear_reentries']}次在rawbear和原range入场机会都未刷新前再次入场，{c['next_session_unrefreshed_bear_reentries']}次发生在下一信号日。扰动点平均此类再次入场{t['mean_point_unrefreshed_bear_reentries']:.4f}次；平均{t['mean_point_unrefreshed_in_long_episode']:.4f}次退出和再次入场同处至少8日的状态分歧段。8日仅是原bull H8的描述尺度，不作为额外经济门或剔除条件。原ACF或确认可能中间不通过，不能称完整买入机会持续通过。\n\n"
    text += '原中心的退出—入场统计：\n\n|路线|退出原因|退出次数|下一信号日同路线入场|\n|---|---|---:|---:|\n'
    for g in diagnosis['center_reentries']['groups']:
        text += f"|{g['route']}|{g['reason']}|{g['exits']}|{g['next_session_same_route_entry']}|\n"
    text += '\n## 实际账户收益核对\n\n'
    text += '实际每日净值的对数收益差，按当日收盘真实数量是否大于0分组，各组相加严格等于年度对数收益差。该标签包含当日卖出前的价格变动、成交和费用；双方收盘空仓也可能当日有盈亏。下表给出真实连续账户年度收益，不把分组描述或旧交易利润当作删项后收益。\n\n|自然年|原中心收益|32点平均收益|\n|---|---:|---:|\n'
    for y in range(2020,2027):
        facts = [r['annual_log_gap'][str(y)] for r in diagnosis['points']]
        text += f"|{y}|{facts[0]['center_return']:.4%}|{sum(r['point_return'] for r in facts)/len(facts):.4%}|\n"
    text += '\n## 判断、验证与下一步\n\n'
    text += '此前18/32最早目标分歧涉及TIME，仅覆盖每点最早一次。全部事件显示，入场差异同样重要，不能把TIME解释为全局唯一根因。状态差异可能持续，也会在双方空仓时消失；单步分类和持续机会统计支持检验相互作用，尚未证明任何新机制能保住收益、回撤、频率及亏损年盈利。\n\n'
    text += '下一步最小可证伪方向：仅bear因TIME退出且仍位于原rawbear与range入场机会内时，要求机会刷新后再买。原H、ACF、确认、bull规则及退出优先级保留，新增的是入场记忆，无新增天数或阈值。最强反证是重复买回可能本来有利，阻断会漏反弹并让交易数低于110；原中心仅112笔，频率余量很小。是否改善只能由后续完整账户及原域参数尾部对照证明，本轮未运行该机制。\n\n'
    text += '33账户逐个验证正式证据hash/schema、整个原生请求/结果精确等于缓存、候选身份、参数点序号及源身份；现金、数量、逐日净损益、年末尾仓和年度回报核对。未新增数据、依赖、平台接口、阶段四排名/交接、冻结、PTE或生产操作。原四项经济目标与13维完整参数域保持，诊断不新增硬门。未做仓库全量回归，FULL仅核验已声明证据完整性。\n\n'
    text += '补充方法v1因2019-12-31信号对应2020-01-02有效执行、年度索引未覆盖而停止；没有新账户运行或结果交付。原方法/源码/失败记录保留，v2按有效执行日归年。同时修正“退出在分歧段内”不能替代“退出和再次入场都在同一段内”的口径。\n'
    return text


def main():
    assert not (PROTO/'delivery_reference.json').exists()
    plan = read(PROTO/'plan.json')
    primary = read(RUNS/'diagnosis.json')
    refresh = read(RUNS/'refresh_diagnosis.json')
    assert primary['status'] == refresh['status'] == 'PASS'
    assert file_hash(SRC/'diagnose.py') == plan['source_files']['src/diagnose.py']
    assert file_hash(SRC/'refresh_diagnosis_v2.py') == read(PROTO/'refresh_method_v2.json')['source_sha256']
    tests=[]
    for filename in ('check_ex033.py','check_ex033_refresh.py'):
        path=ROOT/'.tmp'/filename
        completed=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(path)],cwd=ROOT,check=True,capture_output=True,text=True)
        tests.append({'source':path.read_text(encoding='utf-8'),'sha256':file_hash(path),'output':completed.stdout.strip(),'status':'PASS'})
    lint=subprocess.run([str(ROOT/'.venv/Scripts/ruff.exe'),'check',str(SRC)],cwd=ROOT,check=True,capture_output=True,text=True)
    reconstruction={'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    'new_account_evaluations':0,'native_accounts_reused':33,'tests':tests,'ruff':lint.stdout.strip(),
                    'files':{p.relative_to(ROOT).as_posix():{'sha256':file_hash(p),'source':p.read_text(encoding='utf-8')} for folder in (SRC,PRIOR) for p in folder.rglob('*.py')},
                    'versions':{name:version(name) for name in ('numpy','pandas','czsc-strategy-runtime')},
                    'retention':'Original S013 data, prepared bindings, native accounts and old source snapshots required; Git is not the complete data backup.'}
    write(RUNS/'reproduction.json',reconstruction)
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'descriptive diagnosis delivery only','objective_achieved':False,
                                'new_account_evaluations':0,'native_accounts_reused':33,'new_candidates':0,
                                'next':'Bear TIME exit persistent range-opportunity refresh entry mechanism, full account required; frequency risk remains.',
                                'economic_targets':'UNCHANGED'})
    ctx=context(1)
    materials={name:EvidenceRef.from_dict(read(PROTO/filename)) for name,filename in (
        ('primary-method','plan_reference.json'),('primary-diagnosis','diagnosis_reference.json'),
        ('failed-method-v1','refresh_method_reference.json'),('corrected-method-v2','refresh_method_v2_reference.json'),
        ('corrected-refresh-diagnosis','refresh_reference.json'))}
    for name,path in (('technical-failure-v1',PROTO/'refresh_v1_failure.json'),('reproduction',RUNS/'reproduction.json'),('conclusion',RUNS/'conclusion.json')):
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    text=report_text(primary,refresh)
    assert text==report_text(primary,refresh)
    report_path=SRC.parent/'others/report.md'
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(text,encoding='utf-8',newline='\n')
    refs={label:EvidenceRef.from_dict(ref) for label,ref in primary['input_accounts'].items()}
    report=text+'\n## 正式证据引用\n\n'
    for name,ref in {**refs,**materials}.items():
        assert file_hash(ref.resolve(ROOT))==ref.sha256
        report+=f'- [{name}](../../../assets/deliveries/CANDIDATES/29/{ref.path})\n'
    identity=d.CandidateIdentityRef(CandidateKey('S013','C2132'), read(PRIOR.parent/'protocols/plan.json')['controls'][0]['content_sha256'])
    entry=d.CandidateEntry(identity,'原策略不可变对照，仅诊断退出与重新入场连锁','原四门保持；未宣称实质参数改善',(d.EvaluationEvidenceRef(refs['center']),))
    search=d.SearchSummary(plan['name'],'33既有完整原生账户精确复用与事前声明状态/单步/机会刷新诊断',
                           '仅S013既有数据及原13维共同域32点；零新账户/候选/经济硬门',0,0,'没有新候选选择；总目标未达成',
                           ('反复查看的开发池','联合参数与固定历史信息的描述，非干预收益','信号重同步不等于现金重同步'),
                           (materials['primary-diagnosis'],materials['corrected-refresh-diagnosis'],materials['conclusion']))
    payload=d.CandidateSet((entry,),(),(search,),'完成退出与重新入场的描述归因，下一机制仍须完整账户证伪。')
    evidence={}
    for ref in (*refs.values(),*materials.values()):
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path]==ref
        evidence[ref.repository_path]=ref
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,29,
        (d.DeliveryReference.from_dict(plan['mandate']),d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(evidence.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS',validation.to_dict()
    write(PROTO/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','validation':validation.to_dict(),'reference':receipt.reference.to_dict(),
                                         'objective_achieved':False,'new_account_evaluations':0})
    print({'delivery':receipt.reference.to_dict(),'FULL':'PASS','new_accounts':0,'objective_achieved':False},flush=True)


if __name__=='__main__':
    main()
