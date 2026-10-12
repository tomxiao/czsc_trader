"""Publish read-only participation review, without new experiment or account."""
from pathlib import Path
import csv
import json
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-frequency-117'
DEST=ROOT/'research/S013/reviews/20261012_frequency_117'
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_confirm_execution as base  # noqa: E402
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

def main():
    result=base.read(WORK/'review.json')
    audited=base.read(WORK/'audit_frequency.json')
    peer=base.read(WORK/'peer_review_v2.json')
    counter=base.read(WORK/'counterevidence.json')
    assert audited['status']=='PASS' and peer['status']=='PASS' and counter['status']=='PASS'
    assert audited['review_sha256']==base.digest(WORK/'review.json')
    assert audited['audit_source_sha256']==base.digest(WORK/'audit_frequency.py')
    assert result['candidate_count']==117 and result['distinct_economic_paths']==58
    assert len(result['nearest_ids'])==6 and result['ranking'][0]['positive_closed_trades']==72
    DEST.mkdir(parents=True,exist_ok=False)
    (DEST/'src').mkdir()
    source_names=('review.py','peer_review.py','counterevidence.py','audit_frequency.py','closeout.py')
    for name in source_names:
        with (DEST/'src'/name).open('xb') as stream:
            stream.write((WORK/name).read_bytes())
    for name in ('audit_frequency.json','peer_review_v2.json','counterevidence.json'):
        with (DEST/name).open('xb') as stream:
            stream.write((WORK/name).read_bytes())
    compact={**result,'detailed_recorded_event_review':[{k:v for k,v in r.items() if k!='events'} for r in result['detailed_recorded_event_review']],
        'complete_event_review_sha256':base.digest(WORK/'review.json')}
    base.write(DEST/'review.json',compact)
    columns=['candidate_id','positive_closed_trades','missing_closed_trades','frequency60','net_cagr','full_drawdown',
       'return_gate_margin_pp','minimum_negative_year_return','economic_path_sha256','equivalent_registered_ids','source','source_sha256']
    with (DEST/'ranking117.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        for r in result['ranking']:
            value={key:r[key] for key in columns if key!='equivalent_registered_ids'}
            value['equivalent_registered_ids']=' '.join(result['economic_path_groups'][r['economic_path_sha256']])
            writer.writerow(value)
    ctx=base.common().context(1)
    exp=ExperimentRef('S013','EX098_20261012')
    files=[DEST/'review.json',DEST/'ranking117.csv',DEST/'audit_frequency.json',DEST/'peer_review_v2.json',DEST/'counterevidence.json',
        *sorted((DEST/'src').glob('*.py'))]
    refs={p.relative_to(DEST).as_posix():base.put(ctx,exp,p) for p in files}
    refs['complete_recorded_events.json']=base.put(ctx,exp,WORK/'review.json')
    refs['203_centre_review.json']=base.put(ctx,exp,ROOT/'research/S013/reviews/20261012_new_four_203/results.json')
    report='''# S013：117个仅缺盈利年份频率候选的只读复盘

已完成117个候选的距离排序和已观察交易路径去重，详查最近六个候选及C9070、C3105、C8880。最近六个均72笔、差5笔，却只是一条实际交易路径且买入确认没有启用。当前证据不是“市场完全没有上涨机会”，而是“规则挡住一些事后赢家，也挡住输家，尚未证明能在当时区分并补入足够有效交易”。没有新实验、策略运行、账户、参数修改或数据。

## 排名及真实行为去重

新门要求盈利年份1152交易日合并至少77笔真实闭合，按实际退出日期归年。117个均通过收益、逐年回撤及下跌年份盈利三门，只缺频率。排序先按真实闭合数，收益仅作同距离显示顺序，不添加新的硬门。117个登记ID有58条不同已观察交易路径；这是本区间现金/成交/目标路径的去重，不声称策略源码或未来行为相同。

|候选|盈利年份闭合|缺口|每60日频率|净年化|全期回撤|高于收益门槛的余量|2022收益|2023收益|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    selected=['C0507','C9070','C3105','C8880']
    for cid in selected:
        r=next(x for x in result['ranking'] if x['candidate_id']==cid)
        report+=f"|{cid}|{r['positive_closed_trades']}|{r['missing_closed_trades']}|{r['frequency60']:.6f}|{100*r['net_cagr']:.4f}%|{100*r['full_drawdown']:.4f}%|{r['return_gate_margin_pp']:.4f}个百分点|{100*r['annual']['2022']['return']:.4f}%|{100*r['annual']['2023']['return']:.4f}%|\n"
    report+='''
C0507代表最近的C0507、C0509、C2008、C2009、C9029、C9030。六者去掉身份后完整目标、实际成交、闭合及权益均相同：两种下跌入场范围0.95/0.985、原策略/确认关闭版/迁移副本，不能当成六条独立证据。其年化10.9939%仅高于门槛约0.165个百分点；2022约1.62%、2023约0.55%，增加交易费用和改变路径很容易损失余量。余量是诊断，不是新增筛选门或稳健性认证。

C9070差6笔，收益余量较大，但2023仍只有约0.94%。C3105差7笔，2022和2023中心利润余量更厚，可作不同保护方式对照；不能只根据距离宣布哪个更抗扰动。本次不检查32点。

## 最近候选的瓶颈

这六个候选没有启用买入确认；冷却、固定止损、跟踪止损和动量门也未启用。真实限制主要是上行价格范围、下行自相关、单仓持有和退出后不能同一信号日重入。235张实际订单全部成交，故已发出的交易不是被限价大量阻挡。

C0507在盈利年份的1152个入场执行日中，执行前已有仓位315日（27.34%）、接受入场72日、只因范围拒绝434日、只因原自相关拒绝330日、两者均不通过1日。后四项发生在实际空仓时；这些是原保存的逐日状态分类，不是新增闭合次数。日级诊断按执行日归年，频率硬门按退出日归年，两种计数不能混用。

把下跌入场范围由0.95放至0.985，全期实际空仓时只改变两个时点的范围资格（2023-04-03、2026-03-02），其中盈利年份一个；二者仍未通过自相关，所以六者实际交易完全相同。放宽这个已测范围不是补齐五笔的已有证据。独立从执行价格前缀复算特征的辅助诊断缺少最前99个信号日的预热；主分类使用有SHA认证的原保存决策字段，不用缩窗填补这些特征。

## 有上涨片段，不等于有可提前识别的新增交易

只用原H4/H8作事后价格描述：次日OPEN入、H日后OPEN出，扣双边原10bp。没有运行修改后规则、模拟状态退出或计算新增账户。

|C0507实际空仓拒绝类别|有完整未来价签数|事后扣固定费用为正|价签均值|
|---|---:|---:|---:|
|价格范围拒绝|434|194|−0.1657%|
|原自相关拒绝|329|160|+0.1304%|

范围外有赢家，但整类平均为负，支持范围门有保护作用；自相关拒绝类有微弱正均值，但不足一半价签为正、重叠严重，未校正反复选择，也不是因果预测或实际利润。不能据均值取消整条过滤。

进一步只保留原实际始终空仓、没有任何原成交、次日OPEN满足已知1%限价、固定窗口价格扣费为正、价签退出属于盈利年份的片段，再用最早结束规则去重，C0507事后能挑出69个不重叠片段。**69是看完未来价格才能挑出的价格片段，不是69笔有效机会，更不是可以补入的真实交易。**未核验若改变原规则，新增交易的范围/状态提前退出、资金整手、成本、实际闭合和后续路径是否仍满足其余三门。这个描述只说明历史不缺上涨片段，不能证明有可兑现且可提前识别的五笔增量。

限价只作已知报价与OPEN的必要可行性描述，没有下单或撮合。其网格须与原真实BUY订单独立核对；本报告和完整审计逐值核对相关计算。非1%策略不是这组详查候选，本次没有规范旧参数。

## 既有真实对照的最强反证

既有候选是真实完整账户对照，不是本次创建的实验；以下收益差不是孤立取消门后的因果收益。

1. C2008关闭确认72笔、年化10.99%；C2308只对状态退出后重入增加确认，降为70笔、年化升至12.31%，两个下跌年收益也改善。确认确实曾拒绝控制账户一笔后来赚1.16%的交易，但也拒绝亏损交易；不能把控制赢家的收益相加当成可追回利润。
2. C2308至C3105增加普通上行确认后仍70笔，年化升至12.59%；可链接的三个被拒绝控制账户闭合交易全部亏损。这反证确认只会降低参与、没有质量价值。
3. C8880至C9070允许短期替代确认，盈利年闭合68至71，年化却17.13%至15.03%。替代来源10笔实际闭合5赢5亏，合计净损约9.14万元；其中8笔在盈利年份退出，但整个账户只净增加3笔，因为新入场替换和阻挡了部分旧交易。不能把独有交易数全部算成净新增频率或净新增收益。

因此，规则明确拒绝过实际控制账户中的赢家，局部漏过好交易是事实；同时过滤有收益和下跌期保护价值。当前更准确的问题是有没有当时可识别的有效增量，而不是有没有任何事后上涨时点。

## 结论与下一步

数字最近的一组缺5笔，但没有确认瓶颈、收益余量很薄；C9070的确认拒绝在盈利年已较少，短期替代对照增加参与却伤收益。不能以“差几笔”视为简单补交易即可解决。

建议保留C0507作无确认的频率边界对照，以C9070及C3105作收益保护不同的参照，优先在原范围和自相关拒绝类别中找可在T日区分的子类，并用既有对照检查是否替换旧赢家。该建议是待验证问题，不是新机制成功证据；当前继续暂停，不启动新实验或参数优化。

## 范围与核验

全117排序及路径去重已核对；详细诊断9个编号，最近6个行为相同；其他候选没有逐一做新增机会预测。全数据为S013原开发池，年度涨跌仅事后分析；没有扩大数据、生成新signals、账户或改变登记资格。事后价签不等于策略自检，也不替代32点评价。

完整逐时点描述发布为独立不可变资产；Git中的review.json为不含重复逐时点events的摘要，并保留完整资产SHA。源码原件保存；必要复算应按原相对路径恢复，不能据归档移动路径改变输入范围。

## 明细与证据

[117行距离排序](research/S013/reviews/20261012_frequency_117/ranking117.csv)，以下为正式关联证据（项目根目录相对路径）：

'''
    report+=''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    evidence=tuple(EvidenceRef.from_dict(ref) for ref in refs.values())
    summary=m.SearchSummary('S013-117-frequency-readonly-review','已有117中心的距离/路径/原记录和既有A-B只读复盘',
        '0新评价/配置；事后固定H价签为描述，不生成新策略和账户',0,0,
        '最近72笔六ID实际一条路径；非确认瓶颈；有被拒绝上涨片段，尚无可提前识别并保留其余三门的增量证据',
        ('事后价签及控制赢家不是可追回利润','不检查32点，不选择PTE，不更改资格，研究暂停'),evidence)
    revision=max(int(p.name) for p in (ROOT/'research/S013/deliveries/CANDIDATES').iterdir() if p.name.isdigit())+1
    predecessor=m.DeliveryReference.from_dict(base.read(ROOT/'research/S013/assets/deliveries/MANDATE/7/receipt.json')['reference'])
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.CANDIDATES,revision,(predecessor,)),
        m.DeliveryContent(m.CandidateSet((),(),(summary,),'117中心只读复盘，无新达标或稳健性资格'),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validated=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    assert validated.status.value=='PASS'
    base.write(DEST/'delivery_reference.json',receipt.reference.to_dict())
    base.write(DEST/'delivery_validation.json',validated.to_dict())
    base.write(DEST/'evidence_references.json',refs)
    formal=ROOT/f'research/S013/deliveries/CANDIDATES/{revision}/report.md'
    with (DEST/'report.md').open('xb') as stream:
        stream.write(formal.read_bytes())
    assert (DEST/'report.md').read_bytes()==formal.read_bytes()
    base.write(DEST/'report_copy_verification.json',{'status':'PASS','formal':formal.relative_to(ROOT).as_posix(),
        'copy':(DEST/'report.md').relative_to(ROOT).as_posix(),'formal_sha256':base.digest(formal),
        'copy_sha256':base.digest(DEST/'report.md'),'formal_bytes':formal.stat().st_size,
        'copy_bytes':(DEST/'report.md').stat().st_size,'exact_bytes':True})
    print({'CANDIDATES':revision,'FULL':'PASS','report_copy':'EXACT','ranked':117,'economic_paths':58,
           'new_experiments':0,'new_strategy_runs':0,'new_accounts':0},flush=True)

if __name__=='__main__':
    main()
