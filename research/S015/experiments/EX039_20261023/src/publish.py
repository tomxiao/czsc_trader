"""Publish standalone-role diagnostics without strategy qualification."""
from hashlib import sha256
from standalone import ROOT,HERE,EX,read,save,context,material
from czsc_trader.application import RepositoryContext,publish_evidence,validate_experiment
from czsc_trader.research_tools import EvidenceRef,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope
def main():
    assert not (HERE/'others/published_refs.json').exists();assert read(HERE/'others/independent_audit.json')['status']=='PASS'
    r=read(HERE/'others/results.json');out=['# S015 独立价格路径与波动信息','', 'Status: COMPLETED','',
      'EX036–38选择历史已公开。本轮固定path4、volatility4、combined8，移除旧涨跌幅及量价压力输入；持有职责保留当时已知浮盈亏。8目标×3新模型，96次新拟合，另复现96次基线拟合；无账户、寻优或候选。','',
      '四折前推且训练标签已知日早于测试首日；原434日已经研究，不能称独立样本。风险阈值为各折训练拟合预测中位数，收益/持有阈值为零。下表识别亏损及遗漏盈利均为金额占比，风险模型使用同事件net3实际损益。','',
      '| 目标 | 模型 | MSE改善对均值/量价基线 | 参与数 | 识别亏损 | 遗漏盈利 | 参与事件均值 |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for target,models in r.items():
        for name in ('legacy','path','volatility','combined'):
            z=models[name];u=z['utility'];out.append(f"| {target} | {name} | {100*z['mse_gain_vs_constant']:.3f}% / {100*z['mse_gain_vs_legacy']:.3f}% | {u['selected']['n']} | {100*u['caught_loss_fraction']:.2f}% | {100*u['missed_profit_fraction']:.2f}% | {100*u['selected']['mean']:.4f}% |")
    out+=['','## 判断及反证','',
      '路径三日收益用途不依赖旧基线才出现：误差较训练均值小0.653%，较量价基线小3.661%；选209事件，平均净收益0.3006%，识别31.07%亏损且遗漏24.30%盈利（基线30.76%/34.79%）。但误差和金额差块区间跨0，最后一折选中均值−1.6677%，不能称稳定收益机制。','',
      '四个已知涨跌背景均完整报告，没有按结果裁切规则。path/net3在过去5日上涨两格平均+0.9607%和+0.7691%，过去5日非正两格为−0.3524%和−0.1582%。这不支持“效果仅来自下跌反弹”的解释，但也不能用事后看到的上涨背景直接建立新门槛，或宣称已识别真实订单流因果。','',
      '入场日path选择194/326事件，识别41.96%亏损、遗漏28.18%盈利。较旧基线少遗漏4.44个百分点盈利，同时少识别6.02个百分点亏损，保留净额差约−1693元（重叠事件合计）。误差改善不等于用途全面改善；末折亏损，尚无稳定新增入场日保护组件。入场日只扣买费，不等于完整交易净收益。','',
      '波动loss3风险表达独立预测比均值好1.728%、比旧基线好0.948%；筛选163事件，识别64.05%亏损、遗漏45.14%盈利。其drawdown3误差比均值好1.089%，却比旧基线差5.552%，说明风险用途仍更适合作为辅助而非独立收益驱动。风险阈值取训练拟合分布中位数，存在校准限制。','',
      '直接把路径与波动列合入一个收益预测器没有稳定增加价值。hold1略有有利结果，hold3独立模型误差更差，且持有标签是固定队列的延迟卖出增量，不是实际策略持仓；未确认稳定退出组件。','',
      '11,584项独立审计通过：全部192次拟合、阈值、四格背景、用途、区间。首个运行因旧模块依赖原目录失败，发生于所有拟合之前；原冻结脚本未改，另发布并认证加载修正，仅以相同字节的原位置import，详见补充协议。','',
      '下一步仅做固定职责合成诊断：收益机会与风险筛选分别预测后取交集，检查是否真有互补，以及遗漏盈利和机会密度。它与把全部列塞入一个预测器不同；仍非连续账户或策略验收。','',
      '证据：[协议](protocols/standalone.json)、[技术补充](protocols/loader_correction.json)、[全部结果](others/results.json)、[预测](others/predictions.csv)、[审计](others/independent_audit.json)。']
    (HERE/'report.md').write_text('\n'.join(out)+'\n',encoding='utf-8',newline='\n');refs=[EvidenceRef.from_dict(v) for v in read(HERE/'others/input_refs.json').values()];materials={}
    for sub in ('src','protocols','others'):
        for p in sorted((HERE/sub).glob('*')):
            if p.suffix in ('.py','.json','.csv','.md'):
                ref=material(p);materials[f'{sub}/{p.name}']=ref.to_dict();refs.append(ref)
    rr=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    v=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert v.status.value=='PASS',v.issues
    save(HERE/'others/published_refs.json',{'report':rr.to_dict(),'materials':materials,'validation':v.to_dict()});print('EX039_PUBLISHED',flush=True)
if __name__=='__main__':main()
