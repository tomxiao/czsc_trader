"""Close the authorized construction study without promoting failed centers."""
import json,sys
from hashlib import sha256
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(BASE/'EX042_20261023/src'))
import accounts as a
from czsc_trader.application import RepositoryContext,assemble_delivery,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,EvidenceRef
from czsc_trader.research_tools import delivery as d
def read(p):return json.loads(p.read_bytes())
def percent(x):return f'{x:.3%}'
def main():
    assert not (HERE/'others/delivery_validation.json').exists()
    summary=read(HERE/'others/search_summary.json');assert summary['joint_pass']==0
    assert summary['total_configurations']==159 and summary['standard_accounts']==318
    assert read(HERE/'others/summary_audit.json')['status']=='PASS'
    for key,h in summary['source_hashes'].items():assert sha256((BASE/key).read_bytes()).hexdigest()==h
    publications={};refs=[]
    for n in range(42,48):
        home=BASE/f'EX{n:03d}_20261023';pub=read(home/'others/published_refs.json');publications[n]=pub
        assert pub['validation']['status']=='PASS'
        refs.append(EvidenceRef.from_dict(pub['report']))
        for v in pub['evaluation_refs']:refs.append(EvidenceRef.from_dict(v))
        for k in ('others/results.json','others/account_audit.json'):
            ref=EvidenceRef.from_dict(pub['materials'][k]);assert ref.resolve(ROOT).read_bytes()==(home/k).read_bytes();refs.append(ref)
    receipt=read(ROOT/'research/S015/deliveries/CANDIDATES/4/receipt.json')
    path=ROOT/'research/S015/assets/deliveries/CANDIDATES/4/delivery.json'
    assert sha256(path.read_bytes()).hexdigest()==next(x['sha256'] for x in receipt['files'] if x['path']=='delivery.json')
    prior=d.CandidateSet.from_dict(read(path)['content']['payload']);assert not prior.handoff
    best,low=summary['best_return'],summary['lowest_dd']
    text=['# S015 阶段三交付：价格信息构造域已检验，合格候选仍为零','',
      'Status: COMPLETED','',
      '已完成本轮获授权的阶段三构造与中心检验；产出合格策略的总体目标未达成。CANDIDATES/5交接集合为空。没有进入阶段四、选型、冻结或PTE。',
      '',f"EX042—EX047共6轮、159个参数身份、318个标准窗口账户，另有4个串并行技术重复账户。434日原中心目标通过{summary['full_center_pass']}个；415日收益单门通过{summary['common_return_pass']}个、回撤单门通过{summary['common_dd_pass']}个、联合中心通过0个。159不是159个独立信息或独立验证样本。",'',
      '## 达标与差距','',
      '415日原目标为净收益严格大于91.5802915%、最大回撤严格小于7.2486637491%；完整434日同时保留原年化、回撤与真实闭合频率要求。两项严格比较不能相互补偿，全部按未取整值判断。',
      '', '| 代表结果 | 模式 | 净收益 | 最大回撤 | 60日闭合中位 | ≥3笔窗口 | 434中心 | 415双门 |',
      '| --- | --- | ---: | ---: | ---: | ---: | --- | --- |']
    displayed={x['candidate']:x for x in [best,low,*summary['full_center_candidates']]}
    for r in displayed.values():
        p=r['parameters'];dual=r['common_return_pass'] and r['common_dd_pass'];text.append(f"| {r['candidate']} | {p['family']}/{p['mode']}/{p['exit_rule']}/{p['hold']}日 | {percent(r['net_return'])} | {percent(r['dd'])} | {r['frequency_median']:.0f} | {r['frequency_good']}/375 | {'通过' if r['full_pass'] else '未通过'} | {'通过' if dual else '未通过'} |")
    text+=['',f"最高收益配置{best['candidate']}净收益{percent(best['net_return'])}，415收益门减去实测为{(0.9158029150000013-best['net_return'])*100:.3f}个百分点；全域最低回撤配置{low['candidate']}的回撤为{percent(low['dd'])}，实测减去回撤上限为{(low['dd']-0.07248663749114126)*100:.3f}个百分点，它的净收益为{percent(low['net_return'])}。这两个有符号差额为正表示仍欠缺，为负表示超过单项要求；两个极值来自不同配置，不能拼接成一套策略。",'',
      '## 本轮构造与有证据的边界','',
      'A只使用价格路径或波动转换表达；B加入过去1/5日收益、20日波动/振幅与当日量价压力控制。path表示预测三日净收益非负才允许入场；risk表示预测风险不高于当时训练预测中位数才允许；and要求两者同时满足。固定退出与许可失效退出分别检验，信号在T收盘形成，T+1执行。',
      '', '54个固定退出配置完整覆盖六种家族/许可模式的1—9日期限。当前单持仓周期中，持有10日及以上因闭合频率的结构上界不能达到原中位数要求，详见EX044；这不是擅自增加淘汰门。',
      '', '许可失效退出的六条历史许可序列最长连续长度为16、18、8、22、24、13日。每条的1日至最长长度共101个期限均有正式账户证据；更大的上限在这个已认证历史输入及固定模型下产生同一交易意图。另有4个已测超界参数身份，故合计159而非155。这一结论不外推至未来或其他模型、阈值。',
      '', '本轮穷尽的是上述固定组件、固定训练与许可阈值、固定全仓下的退出构造域，不是全部价格行为策略、所有仓位或所有统计模型。模型系数只用标签已成熟且早于生效日的数据学习；至少30样本后首次生效于2025-02-27，每20交易日更新，共80套拟合。它是截止2026-10-21的历史重放，不是可部署的在线更新系统。',
      '', '两个账户窗口各自从10万元空仓开始，首次模型生效晚于二者起点，因而每个配置在两窗口后续交易及净收益/回撤相同。年化分母和频率窗口不同；两窗口不能算两份独立验证。',
      '', '## 研究判断','',
      '阶段二的有限预测用途没有被本轮技术审计否定，但没有兑现为满足目标的账户收益。期限和退出对结果影响显著，许可失效退出并非普遍改善；A-risk的7日固定退出优于对应提前退出，B-path部分期限则相反。组件组合必须按真实资金占用、机会排斥和成本评价，不能由独立事件平均收益直接推导账户成绩。',
      '', '入场日及持有期损益归因保留在各账户审计中。T收盘的风险判断不能挽回已经发生的当日损失；提前退出最多改变下一交易日之后的仓位。没有把事后删掉亏损交易或拼接不同策略极值作为可执行结果。',
      '', '建议结束本组固定模型的期限及退出调参，不进入阶段四。理由是该有限构造域已经覆盖，全部原型仍未同时满足既定联合目标；不限额度不代表应在同一开发池不断试到偶然通过。下一步建议回到收益机制诊断，先核验更换信息或模型为何应增加可交易优势，再决定是否启动新的组件路线。现结果不能证明所有价格信息无效，也不能证明S015已经形成独立于S011的收益机制。',
      '', '## 证据、局限与保存','',
      '各实验独立核验实际输入、候选实现身份、预测/许可/意图、逐日现金及仓位、成交手续费、净收益回撤和真实CLOSED频率。实际使用的OHLC、金额与日线字段一致；未消费的盘中Volume有429/3464行浮点尾差，最大28股，保留原始差异，未宣称全部数据身份完全相同。',
      '', '时序核验不能替代历史逐条发布/修订时点认证。开发池已反复观察，训练和参数选择均属于研究选择历史。逐年及252日滚动切片继承原账户资本与持仓，仅作诊断，不新增硬门。联合中心未通过，没有运行本轮阶段四32点扰动或费用压力；技术报告/交付PASS不等于策略经济验收。',
      '', '117个历史登记身份及原资格证据保持不变；本轮失败原型不登记成候选，不膨胀当前合格数。当前待选型、待冻结均为0。预算仍为不限轮数，本轮完成6轮，停止理由是研究结论与阶段边界，不是额度耗尽。',
      '', '以下证据随正式交付引用保存；Git保存研究源码、报告和引用，assets/evidence与assets/deliveries须独立保存。', '']
    for n in range(42,48):text.append(f'- [EX{n:03d}报告](../../../experiments/EX{n:03d}_20261023/report.md)')
    text+=['- [159配置完整汇总](../../../experiments/EX047_20261023/others/all_centers.csv)','- [统计及时间切片](../../../experiments/EX047_20261023/others/search_summary.json)']
    report='\n'.join(text)+'\n';(HERE/'others/stage3_report.md').write_text(report,encoding='utf-8')
    ex=a.ExperimentRef('S015',HERE.name)
    for p in (Path(__file__),HERE/'others/stage3_report.md',HERE/'others/search_summary.json',HERE/'others/all_centers.csv'):
        refs.append(a.material(ex,p))
    refs.append(EvidenceRef.from_dict(publications[44]['materials']['others/frequency_bound.json']))
    for key in ('others/runtime_checks.json','others/summary_audit.json'):
        refs.append(EvidenceRef.from_dict(publications[47]['materials'][key]))
    searches=[]
    for count in summary['counts']:
        n=int(count['experiment'][2:5]);pub=publications[n]
        searches.append(d.SearchSummary(f'EX{n:03d}_price_information_construction',f'EX{n:03d}事前固定构造域与公开TDR账户','原434/415独立初始本金，固定价格表达与历史学习，原目标不变',count['account_scenarios'],count['new_configurations'],'本轮联合中心未通过，完整结果及负面证据保留',('已见开发池，选择历史不能由时间因果核验消除。','技术重复另列，不计新配置；阶段四未执行。'),(EvidenceRef.from_dict(pub['report']),EvidenceRef.from_dict(pub['materials']['others/results.json']))))
    payload=d.CandidateSet((),(),(*prior.searches,*searches),'阶段三6轮159参数身份318标准账户，联合中心0；当前交接为空，未进入阶段四。')
    parents=tuple(d.DeliveryReference.from_dict(read(ROOT/f'research/S015/deliveries/{s}/{r}/receipt.json')['reference']) for s,r in [('CANDIDATES',4),('COMPONENTS',12),('MANDATE',3)])
    for ref in refs:ref.resolve(ROOT)
    repo=RepositoryContext.discover(ROOT)
    result=assemble_delivery(repo,d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.CANDIDATES,5,parents),d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(dict.fromkeys(refs))))
    assert result.validation.status.value=='PASS',result.validation.issues
    a.save(HERE/'others/delivery_validation.json',{'delivery':result.receipt.reference.to_dict(),'assembly':result.validation.to_dict(),'qualified_candidates':0,'configurations':159,'standard_accounts':318,'technical_repeat_accounts':4})
    intent=read(ROOT/'research/registrations/S015/family.json')['research_intent']
    budget={**intent['experiment_budget'],'authorized':None,'completed':6,'remaining':None,'unlimited':True}
    intent.update(current_candidates=result.receipt.reference.to_dict(),current_experiment=ex.to_dict(),current_phase='阶段三完成：固定价格模型退出构造域已覆盖，联合中心0',proposal_path='research/S015/experiments/EX042_20261023/protocols/stage3_plan.json',experiment_budget=budget,qualified_candidate_count=0,pending_selection_candidate_count=0,pending_freeze_candidate_count=0,selected_candidate=None,next_gate='建议结束当前固定组件的期限/退出调参，回到收益机制诊断；阶段四未执行且不自动进入。新阶段或新增数据源须确认。')
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户批准阶段三自主执行，6轮159参数身份318标准账户完成；联合中心0，发布CANDIDATES/5空交接，保留全部失败及域边界证据。')
    print('CANDIDATES_5_PASS_NO_QUALIFIED_CENTER',flush=True)
if __name__=='__main__':main()
