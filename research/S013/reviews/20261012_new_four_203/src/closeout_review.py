"""Publish 203-centre derived review; no experiment/account/registry mutations."""
from hashlib import sha256
from pathlib import Path
import csv
import json
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-new-four-203'
DEST=ROOT/'research/S013/reviews/20261012_new_four_203'
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_confirm_execution as base  # noqa: E402
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

def main():
    result=base.read(WORK/'results.json')
    audit=base.read(WORK/'audit.json')
    assert result['candidate_count']==203 and audit['status']=='PASS'
    assert audit['independently_verified_candidates']==203 and not audit['passed_candidates']
    assert result['qualified_count']==0 and audit['gate_counts']==result['gate_pass_counts']
    assert audit['results_sha256']==base.digest(WORK/'results.json')
    DEST.mkdir(parents=True,exist_ok=False)
    (DEST/'src').mkdir()
    for name in ('check_203.py','audit_203.py','closeout_review.py'):
        with (DEST/'src'/name).open('xb') as stream:
            stream.write((WORK/name).read_bytes())
    for name in ('results.json','audit.json'):
        with (DEST/name).open('xb') as stream:
            stream.write((WORK/name).read_bytes())
    metadata=ROOT/'.tmp/s013-new-goal/registered_inventory/metadata.json'
    with (DEST/'execution_metadata.json').open('xb') as stream:
        stream.write(metadata.read_bytes())
    fields=['candidate_id','net_cagr','full_drawdown','positive_year_closed_trades','positive_year_sessions',
       'positive_year_frequency60','return_pass','annual_drawdown_pass','positive_year_frequency_pass',
       'negative_year_profit_pass','four_joint_pass','strategy_premium_1pct','original_limit_premiums',
       'year2022_net_return','year2023_net_return','source','source_sha256','source_schema_version']
    with (DEST/'centres.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for row in result['rows']:
            e,v=row['economics'],row['gates_v2']
            gates=v['gates']
            writer.writerow(dict(zip(fields,[row['candidate_id'],e['net_cagr'],e['full_drawdown'],
              v['positive_closed_cycles'],v['positive_sessions'],v['positive_frequency60'],gates['return'],
              gates['annual_drawdown'],gates['positive_buyhold_year_frequency'],gates['negative_buyhold_year_profit'],
              v['qualified'],row['strategy_premium_1pct'],json.dumps(row['payload_premiums'],sort_keys=True),
              e['annual']['2022']['return'],e['annual']['2023']['return'],row['source'],row['source_sha256'],row['schema_version']],strict=True)))
    other_three=[r for r in result['rows'] if all(v for k,v in r['gates_v2']['gates'].items() if k!='positive_buyhold_year_frequency')]
    frequency=[r for r in result['rows'] if r['gates_v2']['gates']['positive_buyhold_year_frequency']]
    assert len(other_three)==117 and len(frequency)==8
    assert all(not r['gates_v2']['gates']['negative_buyhold_year_profit'] for r in frequency)
    summary={'status':'INDEPENDENTLY_VERIFIED','candidate_count':203,'centre_new_four_pass':0,
        'gate_pass_counts':result['gate_pass_counts'],'other_three_pass_but_frequency_fail':117,
        'frequency_pass_but_negative_year_profit_fail':8,'same_1pct_strategy_candidates':182,
        'different_original_strategy_premium_candidates':21,'new_accounts':0,'new_experiments':0,
        'parameters_changed':0,'old_evidence_changed':0,'parameter32_checked':False,'research_remains_paused':True}
    base.write(DEST/'summary.json',summary)
    ctx=base.common().context(1)
    exp=ExperimentRef('S013','EX098_20261012')
    files=[DEST/'results.json',DEST/'audit.json',DEST/'execution_metadata.json',DEST/'centres.csv',DEST/'summary.json',
        *sorted((DEST/'src').glob('*.py'))]
    refs={p.relative_to(DEST).as_posix():base.put(ctx,exp,p) for p in files}
    refs['fixed_benchmark_native']=result['benchmark']['reference']
    refs['historical_review_inventory']=base.put(ctx,exp,ROOT/'research/S013/reviews/20261012_existing_candidates/review.json')
    report=f'''# S013：203个已有候选的新四门中心检查

已完成203/203，中心同时通过新四门的候选为0个，主计算与独立复核一致。本次保留每个候选原规则及实际成交账本，统一使用已认证固定1% LimitBuyHold基准；没有新实验、账户、拟合、优化或32点评价，研究继续暂停。当前98轮研究额度没有增加或重启。

## 检查口径和结果

按203个已登记候选ID逐一统计，不把实验轮数、参数扰动点或未登记策略算入。只检查中心，四门必须同时通过，不以单项达标或3/4代替。共同区间2020-01-02至2026-09-30，共1636交易日；510500.SH、100万元、单侧10bp、HFQ2019-12-31锚0.2803、不叠加现金分红、现金做多无杠杆。

|新四门|单独通过数量|判定|
|---|---:|---|
|整体净年化|147/203|策略至少同期正buyhold的1.5倍，本池约10.829%|
|逐自然年最大回撤|195/203|每一年策略回撤严格小于buyhold，包含上年末权益|
|buyhold盈利年份合并交易频率|8/203|1152日实际闭合至少77笔，即每60日至少4笔|
|buyhold亏损年份策略盈利|134/203|2022及2023实际连续净收益均严格为正|
|四门联合|0/203|四项全部通过|

117个候选同时通过收益、年度回撤和下跌年份盈利三门，但盈利年份频率不足。频率达标的8个候选全部未通过下跌年份盈利门。说明当前这批原策略的矛盾集中在有效参与与下跌期保护之间，不能据此证明目标不可能实现。

盈利年份为2020、2021、2024、2025及2026截至研究截止日，只作事后验收，不输入策略。闭合交易按实际退出日期归年，未闭合持仓不计；2026不是完整自然年。全期频率仅诊断。

## 旧证据与统一执行合同的区别

旧版本也保存完整策略账本。本次检查用最新可得的195份schema5及8份schema6中心来源，逐一认证源SHA、候选身份及数据身份。仅在内存读取旧schema5时，将不存在的可选parameter_point明确读取为None；不修改历史文件、schema、结果哈希或登记资格，不声称旧原生证据已升级为schema6。

全部203的日期、收盘价、执行日线和分时价格与固定基准精确一致，资金、费用和计价一致，因此可以保留策略账本，独立采用当前基准重新判定经济门。原NextOpenBuyHold曲线仍保存在旧结果中；新比较曲线及来源单独列出，不改写它。

182个策略原买入溢价即1%，本次检查全部未联合达标。其余21个原溢价为0.2%、0.5%、1.5%或2%，保持原规则也全部未联合达标；它们未被规范成1%后重跑。因此0/203是原203策略对当前固定基准的新门事后检查结果，不是203套已统一改参并重新执行的结果。若改这21个候选的溢价，需要另外真实重测，不能修改账本推算，也不能继续沿用“原策略未改”的说法。

## 独立核验与限制

独立逐项核验203个候选身份、来源、43005笔实际成交及21397个闭合周期，重算费用、现金、数量、权益、退出日期、连续年度收益及回撤。最大现金/权益误差为{audit['maximum_cash_mark_error']:.12g}元，主审四门数及逐候选结果完全一致。技术和证据核验通过不等于经济达标。

本次不运行标准32点、双费用或完整五项自检，不继承旧稳健性资格；没有新中心通过，因此没有进入后续稳健性确认。开发池反复研究和候选选择偏差仍存在。

下一步建议先围绕117个仅缺盈利年频率者与8个频率达标但下跌期亏损者，复盘哪些机会被拒绝、哪些交易消耗收益。此次只交付检查，保持暂停，未授权的新机制实验不启动。

## 频率达标的8个候选

|候选|净年化|全期回撤|盈利年闭合数|2022收益|2023收益|收益门|年度回撤门|下跌年盈利门|
|---|---:|---:|---:|---:|---:|---|---|---|
'''
    for r in frequency:
        e,g=r['economics'],r['gates_v2']['gates']
        report+=f"|{r['candidate_id']}|{100*e['net_cagr']:.4f}%|{100*e['full_drawdown']:.4f}%|{r['gates_v2']['positive_closed_cycles']}|{100*e['annual']['2022']['return']:.4f}%|{100*e['annual']['2023']['return']:.4f}%|{g['return']}|{g['annual_drawdown']}|{g['negative_buyhold_year_profit']}|\n"
    report+='\n## 逐候选明细与证据\n\n[203行检查表](research/S013/reviews/20261012_new_four_203/centres.csv)含各门、实际收益、频率、原溢价和来源SHA；完整JSON保留全部年度和新旧比较口径。\n\n'
    report+=''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    evidence=tuple(EvidenceRef.from_dict(ref) for ref in refs.values())
    search=m.SearchSummary('S013-203-recorded-centres-new-four-review','203既有中心账本事后新门审查',
        '只读取已有完整账户；统一固定基准；0新增评价、0新配置、0改参',0,0,
        '203中心四门联合通过0；117个只缺频率；8个频率通过者全部下跌年盈利失败',
        ('21个策略原溢价不同，不冒称规范成1%重跑','不检查32点，不改变旧登记资格'),evidence)
    revision=max(int(p.name) for p in (ROOT/'research/S013/deliveries/CANDIDATES').iterdir() if p.name.isdigit())+1
    predecessor=m.DeliveryReference.from_dict(base.read(ROOT/'research/S013/assets/deliveries/MANDATE/7/receipt.json')['reference'])
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.CANDIDATES,revision,(predecessor,)),
        m.DeliveryContent(m.CandidateSet((),(),(search,),'203原中心新四门联合通过0，保留历史资格与原证据'),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validated=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    assert validated.status.value=='PASS'
    base.write(DEST/'delivery_reference.json',receipt.reference.to_dict())
    base.write(DEST/'delivery_validation.json',validated.to_dict())
    base.write(DEST/'evidence_references.json',refs)
    formal=ROOT/f'research/S013/deliveries/CANDIDATES/{revision}/report.md'
    with (DEST/'report.md').open('xb') as stream:
        stream.write(formal.read_bytes())
    assert (DEST/'report.md').read_bytes()==formal.read_bytes()
    base.write(DEST/'report_copy_verification.json',{'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),
        'copy':(DEST/'report.md').relative_to(ROOT).as_posix(),'formal_sha256':base.digest(formal),'copy_sha256':base.digest(DEST/'report.md'),
        'formal_bytes':formal.stat().st_size,'copy_bytes':(DEST/'report.md').stat().st_size,'exact_bytes':True})
    print({'CANDIDATES':revision,'FULL':'PASS','report_copy':'EXACT','checked':203,'centre_new_four_pass':0,'new_accounts':0,'new_experiments':0},flush=True)

if __name__=='__main__':
    main()
