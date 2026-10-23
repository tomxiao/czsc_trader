"""Preview or publish EX040 only; stage-two integration is a separate operation."""
import argparse
from hashlib import sha256
from composition import ROOT, HERE, EX, POLICIES, read, save, context, material
from czsc_trader.application import RepositoryContext, publish_evidence, validate_experiment
from czsc_trader.research_tools import EvidenceRef, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope

def report():
    result = read(HERE / 'others/results.json')
    audit_path = HERE / 'others/independent_audit.json'
    audit = read(audit_path) if audit_path.exists() else None
    audited = audit is not None and audit.get('status') == 'PASS'
    lines = ['# S015 固定收益与风险职责合成诊断', '',
             'Status: ' + ('COMPLETED' if audited else 'IN_PROGRESS'), '',
             '本轮检验两个已有组件是否适合同时作为参与条件。A复用EX039独立路径net3与波动loss3，B复用EX038含历史量价控制的时间顺序net3与波动loss3。各套比较收益许可、风险许可及两者交集；共享旧量价基线和全部事件参考。协议及计算源码在执行前已公开冻结。', '',
             '共同样本为原四个前推段中的323个闭合三日事件；所有规则使用同一事件、同一折和同一实际买入数量。零新增拟合、零阈值/权重/OR搜索、零连续账户与候选。沿用原双侧费用的net3标签，入场日entry只扣买费。训练中位风险阈值沿用已发布预测，不在测试段重新校准。', '',
             '**所有金额都是重复投入10万元的相互重叠事件诊断之和，不是账户收益；不能连乘、年化或拿来对比S011净值。** 四折训练清除未知标签，但这些日期已反复研究，不是新的独立验证样本。', '',
             '## 整体用途与机会代价', '',
             '| 规则 | 参与事件 | 参与均值 | 保留事件净额（元） | 识别亏损金额 | 遗漏盈利金额 | 60日频率上界中位数 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for policy in POLICIES:
        item = result['policies'][policy]; z = item['outcomes']['net3']['all']; f = item['frequency_upper_bound']
        lines.append(f"| {policy} | {z['selected']['n']} | {100*z['selected']['mean']:.4f}% | {z['retained_amount']:.2f} | {100*z['caught_loss_fraction']:.2f}% | {100*z['missed_profit_fraction']:.2f}% | {f['median_max']:.0f} |")
    lines += ['', '## 交集相对单组件新增排除的得失', '',
              '下面比较严格配对。AND是各单组件的子集，新增排除可能同时省下亏损和丢失盈利；净额增量为前者减后者。区间单位为每个共同事件的收益率百分点，采用原434日轴上的20日块、499次抽样、种子13；未校正多项比较和选择历史，不是新的验收门槛。', '',
              '| 比较 | 新排除数 | 省下亏损（元） | 丢失盈利（元） | 保留净额增量（元） | 每事件增量95%区间（百分点） |',
              '| --- | ---: | ---: | ---: | ---: | --- |']
    for pair in ('A', 'B'):
        for role in ('path', 'risk'):
            key = pair + '/AND vs ' + pair + '/' + role; z = result['paired'][key]['net3']['all']; lo, hi = z['ci95_mean_per_common_event']
            lines.append(f"| {key} | {z['removed_n']} | {z['removed_loss_amount']:.2f} | {z['removed_profit_amount']:.2f} | {z['net_retained_amount_increment']:.2f} | [{lo*100:.4f}, {hi*100:.4f}] |")
    lines += ['', '两套AND相对收益组件增加了亏损过滤，但均比单独风险许可少保留事件净额：A少25203.83元，B少27509.30元。参与均值上升与事件总机会增加不是同一结论；不能因交集平均收益更高就认定组件互补或自动选AND。四个整体配对区间均跨零。', '',
              '## 时间与背景反证', '',
              'A/B交集最后一折的保留事件净额分别为−25731.11/−13506.02元，未消除不利时期。删除同一组5个最大绝对net3事件后，两套交集保留净额仍为65535.33/53542.35元；这只说明不是完全由这5项支撑，不证明稳定。', '',
              '| 已知背景 | A交集参与数/均值 | B交集参与数/均值 |', '| --- | ---: | ---: |']
    for state in [key for key in result['policies']['A/AND']['outcomes']['net3'] if key.startswith('state/')]:
        aa = result['policies']['A/AND']['outcomes']['net3'][state]['selected']; bb = result['policies']['B/AND']['outcomes']['net3'][state]['selected']
        lines.append(f"| {state.removeprefix('state/')} | {aa['n']} / {aa['mean']*100:.4f}% | {bb['n']} / {bb['mean']*100:.4f}% |")
    lines += ['', '全部四格均保留，不按结果增加交易背景限制。A在当日与五日均非正时仍亏损；B在当日正、五日非正格仅1个事件，无法作稳定性推断。表达差异和这些分组不能证明与S011账户独立或互补。', '',
              '## 入场日与机会密度', '',
              '| 规则 | 入场日识别亏损 | 入场日遗漏盈利 | 保留入场日净额（元） |', '| --- | ---: | ---: | ---: |']
    for pair in ('A', 'B'):
        key = pair + '/AND'; z = result['policies'][key]['outcomes']['entry']['all']
        lines.append(f"| {key} | {z['caught_loss_fraction']*100:.2f}% | {z['missed_profit_fraction']*100:.2f}% | {z['retained_amount']:.2f} |")
    lines += ['', '入场日与三日完整损益是不同职责：两套交集的入场日盈利遗漏分别59.22%和63.45%，不能称无代价保护。全部规则的275个60日窗口上界都至少3笔；交集上界中位数A为13、B为7。上界以已记录闭合事件、允许同日切换并选择最多不重叠机会计算，仍然乐观；未覆盖最初100个未预测决策，不能宣称原434日实际频率通过。', '',
              '## 阶段二结论与停止边界', '',
              '本轮补齐“单独有用是否意味着组合有用”的关键缺口。路径组件可保留为有限收益筛选证据，波动组件可保留为风险许可证据；交集没有获得相对单独风险许可的明确增量，组合暂不升级为有效完整逻辑。不能据本轮结果继续寻优阈值、OR、权重或状态。', '',
              '建议完成阶段二综合交付，列明可用职责、负面结果及未证实的退出/成交用途。后续若获准进入阶段三，应预先固定有限原型并用连续账户检验行为、收益、回撤和频率；本阶段没有证实任何策略达到MANDATE/3，原资格不变。']
    lines += ['', ('独立审计PASS；审计覆盖与准确计数见原件。' if audited else '独立审计尚未完成，暂不正式发布。'), '',
              '证据：[冻结协议](protocols/composition.json)、[全部结果](others/results.json)、[共同事件决策](others/decisions.csv)、[输入认证](others/input_refs.json)、[独立审计](others/independent_audit.json)。']
    (HERE / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')

def publish():
    assert not (HERE / 'others/published_refs.json').exists()
    assert read(HERE / 'others/independent_audit.json')['status'] == 'PASS'
    report()
    refs = [EvidenceRef.from_dict(value) for value in read(HERE / 'others/input_refs.json').values()]
    files = ['src/composition.py', 'src/publish.py', 'src/audit.py', 'protocols/composition.json',
             'others/protocol_refs.json', 'others/input_refs.json', 'others/results.json',
             'others/decisions.csv', 'others/design_counts.json', 'others/independent_audit.json']
    materials = {}
    for name in files:
        path = HERE / name; assert path.is_file()
        reference = material(path); materials[name] = reference.to_dict(); refs.append(reference)
    published = publish_evidence(context(), ExperimentReportWrite(EX, sha256((HERE / 'report.md').read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, tuple(dict.fromkeys(refs))))
    validation = validate_experiment(RepositoryContext.discover(ROOT), ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS', validation.issues
    save(HERE / 'others/published_refs.json', {'report': published.to_dict(), 'materials': materials, 'validation': validation.to_dict()})
    print('EX040_PUBLISHED', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=('preview', 'publish'))
    {'preview': report, 'publish': publish}[parser.parse_args().mode]()
