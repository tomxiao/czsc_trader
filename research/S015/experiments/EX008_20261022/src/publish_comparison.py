"""Plot, report and publish this fixed comparison without changing prior evidence."""
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import zipfile

from run_comparison import ROOT, EROOT, EX, context, read, save
os.environ['MPLCONFIGDIR'] = str(ROOT / '.tmp/matplotlib-s015-ex008')
os.environ['MPLBACKEND'] = 'Agg'
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import pandas as pd
from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (
    EvidenceRef, MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope,
)


def pct(x): return f'{100*x:.2f}%'


def main():
    data = read(EROOT/'others/assessment.json')
    c,s = data['statistics']['C0031'], data['statistics']['S011-v1']
    assert data['comparative_gate']=='FAIL'
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    fig,axes=plt.subplots(2,1,figsize=(12,7.4),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for label,color in [('S011-v1','#176B87'),('C0031','#D76C30')]:
        a=pd.read_csv(ROOT/data['statistics'][label]['output_dir']/'account_daily.csv')
        dates=pd.to_datetime(a.date)
        net=(a.equity/100000-1)*100
        dd=(a.equity/a.equity.cummax().clip(lower=100000)-1)*100
        axes[0].plot(dates,net,label=label,color=color,lw=1.7)
        axes[1].plot(dates,dd,label=label,color=color,lw=1.3)
        axes[1].fill_between(dates,dd,0,color=color,alpha=.08)
        axes[0].annotate(f'{net.iloc[-1]:.2f}%',(dates.iloc[-1],net.iloc[-1]),xytext=(8,0),textcoords='offset points',color=color,fontsize=10)
    for ax in axes:
        ax.grid(alpha=.18); ax.spines[['top','right']].set_visible(False)
        ax.legend(loc='upper left',frameon=False)
    axes[0].set_title('修复后 S011-v1 与 C0031：完整共同窗口',fontproperties=font,fontsize=16,loc='left',pad=15)
    axes[0].set_ylabel('累计净收益（%）',fontproperties=font)
    axes[1].set_ylabel('距历史高点回撤（%）',fontproperties=font)
    fig.text(.08,.025,'2025-02-06 至 2026-10-21｜初始资金10万元｜单边费用0.1%｜期末不强平',fontproperties=font,fontsize=10,color='#555555')
    fig.tight_layout(rect=(0,.05,1,1))
    fig.savefig(EROOT/'others/comparison.png',dpi=160)
    plt.close(fig)
    rows=[]
    for title,sv,cv in [
        ('累计净收益',pct(s['net_return']),pct(c['net_return'])),
        ('最大回撤幅度',pct(s['drawdown']['magnitude']),pct(c['drawdown']['magnitude'])),
        ('252交易日复合年化收益',pct(s['annualized_return']),pct(c['annualized_return'])),
        ('期末权益',f"{s['final_equity']:,.2f}元",f"{c['final_equity']:,.2f}元"),
        ('Calmar（年化收益/最大回撤）',f"{s['metrics']['calmar']:.2f}",f"{c['metrics']['calmar']:.2f}"),
        ('夏普比率',f"{s['metrics']['sharpe']:.2f}",f"{c['metrics']['sharpe']:.2f}"),
        ('闭合交易数',str(s['metrics']['closed_trades']),str(c['metrics']['closed_trades'])),
        ('胜率',pct(s['metrics']['win_rate']),pct(c['metrics']['win_rate'])),
        ('盈亏比',f"{s['metrics']['win_loss_ratio']:.2f}",f"{c['metrics']['win_loss_ratio']:.2f}"),
        ('实际累计费用',f"{s['fees_paid']:,.2f}元",f"{c['fees_paid']:,.2f}元"),
        ('滚动60日闭合交易中位数',str(int(s['rolling60_median'])),str(int(c['rolling60_median']))),
        ('60日窗口至少3笔覆盖率',f"{pct(s['rolling60_coverage'])}（328/356）",'100%（356/356）')]:
        rows.append(f'| {title} | {sv} | {cv} |')
    yearly=[]
    for sy,cy in zip(data['yearly_slices']['S011-v1'],data['yearly_slices']['C0031'],strict=True):
        yearly.append(f"| {sy['year']}（{sy['start']}至{sy['end']}） | {pct(sy['net_return'])} | {pct(cy['net_return'])} | {pct(sy['slice_drawdown']['magnitude'])} | {pct(cy['slice_drawdown']['magnitude'])} |")
    report=f'''# 修复后 S011-v1 与 C0031：完整共同窗口对照

Status: COMPLETED

RSCH，2026-10-22。已按用户授权重新执行两份独立 TDR 回测，原策略和既有证据保持不变。

**结论：C0031 收益更高、回撤更大，仍未满足“收益和回撤均优于 S011-v1”的必要条件，本轮不推进 C0031 的冻结及 PTE 准入。**

## 口径与身份

共同窗口为 **2025-02-06 至 2026-10-21，415 个交易日**。修复恢复了 S011 原设计首个执行日；本次是两份策略保持原样时的最长共同窗口，不是完整2025自然年。S015 原开发池从2025-01-02起的约定和历史证据仍保留，不在S011合法起点前虚构空仓记录。

两账户均从10万元、零持仓开始；159326.SZ，单边实际成交额费用0.1%，HFQ_RESEARCH研究价格与份额单位、100份整手、DAILY_RANGE_V3价格范围成交，不按成交量约束。保留各自限价与退出规则，期末不强制平仓。收益含期末持仓浮动盈亏，扣除实际已发生费用，不扣尚未发生的未来卖出费用。C0031期末持有{c['terminal_quantity']:,}研究份额，S011期末空仓。

- S011-v1：本地修复后发布，release_hash `5da4a999f28aa699ef60641bc26d34f66e124dda8236063aeeea9b18afa9e89e`。
- S015-C0031：登记内容 `6a6e536c6c2f017c43d238633267c05f1f2b9d647aa22d52506d9e8e0a81d580`，实现与参数未变。
- 两账户执行数据全字段一致，指纹 `{data['common_execution_fingerprint']}`；逐笔实际费用与0.1%一致，起止日和初始账户相同。策略所需输入不同是既有策略定义的差异。
- 本轮沿用当前获批分支，仅做固定策略比较，不调参、不新增候选、不写生产。全部历史已见，独立回测指独立账户运行，不代表新的独立样本外验证。

## 完整账户结果

| 指标 | 修复后 S011-v1 | C0031 |
| --- | ---: | ---: |
{chr(10).join(rows)}

C0031多赚 **{c['final_equity']-s['final_equity']:,.2f}元**，累计收益高 **{data['return_advantage_pp']:.2f}个百分点**；最大回撤却大 **{data['drawdown_disadvantage_pp']:.2f}个百分点**，约为S011的 **{data['drawdown_ratio']:.2f}倍**。收益条件通过、回撤条件失败，二者必须同时满足的总体结果为FAIL。较高的最终净值不能抵消用户单独规定的回撤要求。

![累计净收益与连续回撤](others/comparison.png)

## 回撤发生在哪里

S011最大回撤从2026-07-03的202,573.67元降至07-20的187,889.79元，为7.25%；C0031从2026-06-30的226,645.00元降至同一天07-20的192,480.92元，为15.07%。如峰值连续多日相等，起点取谷底前最后一个等高日。两者截至10-21均未恢复对应峰值。

这表明两者在2026年7月同一阶段遭遇损失，而C0031承受的净值跌幅更大。此处是账户路径事实，不把差异直接归因于某个单一信号，也不将两者解释为有互补价值。

## 年度与滚动诊断

| 连续账户切片 | S011收益 | C0031收益 | S011区间回撤 | C0031区间回撤 |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(yearly)}

年度收益从切片前一交易日权益起算，继承资金与持仓，不重新投入10万元；区间回撤包含切片初始权益，主结论始终使用415日账户完整高点。2025、2026都是实际覆盖区间，首尾不完整年份不年化后混合。本次两个年度切片都表现为C0031多收益、多回撤。

252交易日滚动窗口、步长21日，共8个完整窗口：C0031在8/8个窗口收益更高，也在8/8个窗口回撤更大。最末窗口为2025-09-08至2026-09-21；这些重叠窗口用于说明路径，不是8次独立验证，不新增年度或窗口必须胜出的硬门。

## 与上次408日比较的变化

上次共同窗口从02-17开始，本次恢复02-06起点，多7个交易日。S011新增日期全部空仓，因此累计收益仍为91.58%、最大回撤仍为7.25%；期限增加导致年化指标变化。

C0031累计收益从104.36%变为107.00%，增加2.64个百分点。其首次买入由02-17、1.092元提前到02-14、1.078元；其余成交日期和价格相同，02-17以后目标仓位序列相同，初次资金差异影响后续复投和整手取整。闭合交易数仍为100。这里是固定策略窗口恢复后的账户路径变化，不是调参提升，也不是S011修复改变了C0031源码。

## 验证、限制与下一步

两策略与CLI内置基准技术审计均PASS。额外从账本独立复算收益、含初始资金的连续最大回撤、逐笔费用和滚动交易频率；另一次独立只读复核确认每日权益恒等式及按成交重建期末权益一致。两个账户并行运行，各自原生线程1，回测计算与保存耗时分别约3.58秒和3.94秒。

滚动60日交易中位数≥6笔、至少90%窗口有≥3笔及绝对最大回撤≤25%的单项均满足。**其他既定默认要求没有放宽，也没有宣称本轮全部复验通过。** CLI内置BuyHold与原研究1%限价BuyHold不同，不能据其结果宣称正式基准经济门通过。由于新增必要条件已失败，本轮不追加32点扰动或费用压力，不把旧窗口通过结论转作本窗口全面验收。

研究建议：保留S011作为当前比较基线，C0031保持未获本轮准入的状态。若继续研究，优先提出能降低反弹失败期间亏损、并检验其收益代价的有边界方案；方案评审后再决定新实验。本轮没有冻结、部署、账户切换或PTE生产操作。

证据：[完整数值与原文件哈希](others/assessment.json)、[事前协议](protocols/comparison.json)、[来源归档引用](others/account_archives.json)、[独立复核](others/independent_review.json)。

独立回测：[S011报告](../../../../{s['output_dir']}/report.md) · [S011交互图表](../../../../{s['output_dir']}/chart.html) · [C0031报告](../../../../{c['output_dir']}/report.md) · [C0031交互图表](../../../../{c['output_dir']}/chart.html)。
'''
    (EROOT/'report.md').write_text(report,encoding='utf-8',newline='\n')
    ctx=context()
    refs=[EvidenceRef.from_dict(r) for r in read(EROOT/'others/protocol_evidence.json')['references']]
    archives={}
    for label,stats in data['statistics'].items():
        folder=ROOT/stats['output_dir']
        buffer=BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(folder.iterdir()):
                if p.is_file():
                    assert sha256(p.read_bytes()).hexdigest()==data['source_files_sha256'][label][p.name]
                    archive.writestr(p.name,p.read_bytes())
        ref=publish_evidence(ctx,MaterialEvidenceWrite(EX,label+'_complete_backtest',buffer.getvalue(),'application/zip','zip'))
        refs.append(ref); archives[label]=ref.to_dict()
    save(EROOT/'others/account_archives.json',archives)
    for p in [*sorted((EROOT/'src').glob('*.py')),*sorted((EROOT/'others').glob('*.json')),EROOT/'others/comparison.png']:
        media='image/png' if p.suffix=='.png' else 'text/x-python' if p.suffix=='.py' else 'application/json'
        refs.append(publish_evidence(ctx,MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),media,p.suffix[1:])))
    report_ref=publish_evidence(ctx,ExperimentReportWrite(EX,sha256((EROOT/'report.md').read_bytes()).hexdigest(),
        ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    checked=validate_experiment(ctx.repository,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION))
    assert checked.status.value=='PASS'
    save(EROOT/'others/publication_validation.json',{'status':'PASS','report':report_ref.to_dict(),'validation':checked.to_dict()})
    print('REPORT_PUBLICATION_PASS',report_ref.to_dict(),flush=True)


if __name__=='__main__':main()
