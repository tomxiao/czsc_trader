"""Publish the complete fixed screening experiment and its limitations."""
import json
from pathlib import Path
from hashlib import sha256
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_experiment
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope)

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]
NAMES = {'U': '无筛选', 'B': '量价控制', 'BF': '量价+份额', 'BP': '量价+路径', 'BPF': '量价+路径+份额'}
CHECKS = {'return': '年化收益', 'relative_drawdown': '相对回撤', 'absolute_drawdown': '绝对回撤',
          'frequency_median': '频率中位数', 'frequency_coverage': '频率覆盖'}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def report():
    result = read(HERE / 'others/results.json')
    diagnostics = read(HERE / 'others/account_diagnostics.json')
    audit = read(HERE / 'others/account_audit.json')
    event = read(HERE / 'others/event_metrics.json')
    assert result['new_configurations'] == 7 and result['account_scenarios'] == 14
    assert result['qualified_centers'] == 0 and audit['status'] == 'PASS'
    for name in ('training_audit.json', 'audit_training_final.json', 'runtime_checks.json'):
        assert read(HERE / 'others' / name)['status'] == 'PASS'
    lines = ['# S015 份额与路径信息的固定账户用途对照', '', 'Status: COMPLETED', '',
             'RSCH，2026-10-24。阶段二固定对照完成；新增合格策略0个。份额状态在量价基线上产生有限的账户增量，但延迟三日后大幅退化；路径与份额的组合有条件作用，不能认定两者普遍互补。事件筛选较好不保证连续账户较好。', '',
             '## 固定设计与资金契约', '',
             'U为无预测筛选；B为原5项量价控制；P为4项盘中价格路径；F为20日ETF份额扩张/不变状态，份额是基金单位数量，不能直接当成流入金额。主口径T−1，T−3仅为历史可得性敏感性，不从两者选收益更高的时点。', '',
             '七个配置全部使用CYCLE_TARGET及signal_cash_fraction/entry_cycle，首次采纳按可用现金100%锁定含买费预算和目标份额，补买受余额约束；不每日按权益重配。三日指信号意图年龄，未成交仍消耗年龄，退出意图日不能再入场。固定Ridge10、阈值0、至少30个成熟三日标签、每20日更新；没有搜索阈值、持有天数或选型参数。U与B同日开始可交易。', '',
             '两个窗口分别10万元空仓初始化：434日2025-01-02至2026-10-21；415日2025-02-06至2026-10-21。首次模型2025-02-27，之前均持现，因而两窗后续资金路径、净收益和回撤相同，年化及频率分母不同。不是切片账户，也不是两份独立验证。原1%限价买、市价卖、100份整手、0.001元档位、每侧0.1%费用、期末估值不强平全部保留。', '',
             '## 完整账户结果', '',
             '| 配置 | 份额延迟 | 434/415日净收益 | 最大回撤 | 434日净年化 | 闭合周期 | 60日中位 | ≥3笔窗口/375 | 费用元 | 434日未通过项 |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in result['rows']:
        p = row['parameters']; f = row['runs']['full']; c = row['runs']['s011_common']
        assert f['net_return'] == c['net_return'] and f['dd'] == c['dd']
        failed = '、'.join(CHECKS[k] for k, v in f['checks'].items() if not v) or '无'
        lines.append(f"| {row['candidate_id']} {NAMES[p['family']]} | T−{p['lag']} | {100*f['net_return']:.4f}% | {100*f['dd']:.4f}% | {100*f['cagr']:.4f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']} | {f['fees']:.2f} | {failed} |")
    base = result['rows'][0]['runs']['full']
    lines += ['', f"434日BuyHold净年化{100*base['benchmark_cagr']:.6f}%，最大回撤{100*base['benchmark_dd']:.6f}%；中心要求年化至少{150*base['benchmark_cagr']:.6f}%、回撤≤{80*base['benchmark_dd']:.6f}%且≤25%，频率中位≥6及至少338/375窗达标。415日严格要求净收益>91.58029150000013%、回撤<7.248663749114126%。七臂415两个单门全部未过，联合中心0；32点扰动及费用压力未做，不宣称完整资格。", '',
              '## 组件直接增量与反证', '',
              '- B→BF：收益增加12.1331个百分点，回撤减少0.7827个百分点，少6个闭合周期、少408.02元费用。这是该固定原型与T−1条件下的双向改善；相对无筛选U，BF仅多0.5508个百分点收益，不能称巨大或稳定优势。',
              '- B→BP：收益增加41.1724个百分点，但回撤增加3.7196个百分点；路径有收益机会线索，却没有同时解决风险。',
              '- BF→BPF：收益增加4.9840个百分点、回撤减少0.3730个百分点；但BP→BPF收益减少24.0553个百分点、回撤减少4.8753个百分点。加入份额并非在所有背景都改善目标，两因素有交互。',
              '- 可得性反证：BF改为T−3，收益24.8891%→0.4200%、回撤28.5999%→32.7231%；BPF改为T−3，收益29.8730%→26.2901%、回撤28.2268%→30.0910%。不能把T−1局部优势升级成发布时间可靠的稳定组件。历史份额发布时间/修订PIT未获认证。', '',
              '## 入场当天能识别多少亏损，会错过多少盈利', '',
              '同一389个可比较、已闭合三日事件，每个事件单独投入10万元。入场日损益扣买入费，三日净损益扣双侧费。金额识别率分母分别是全队列负金额绝对值、正金额总和；不是准确率。未成交、末端未闭合独立列出，不当成零收益。', '',
              '| 主口径 | 入场亏损金额识别 | 入场盈利金额遗漏 | 三日亏损金额识别 | 三日盈利金额遗漏 | 许可事件/389 |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    values = {(r['family'], r['label']): r for r in event['rows'] if r['cohort'] == 'all_ready_closed' and r['lag'] == 1}
    for family in NAMES:
        a, b = values[family, 'entry_net'], values[family, 'net']
        lines.append(f"| {NAMES[family]} | {100*a['loss_amount_rejected_fraction']:.3f}% | {100*a['profit_amount_missed_fraction']:.3f}% | {100*b['loss_amount_rejected_fraction']:.3f}% | {100*b['profit_amount_missed_fraction']:.3f}% | {a['allowed']} |")
    e = values['B', 'entry_net']; n = values['B', 'net']
    lines += ['', f"共同入场日金额分母：亏损{e['negative_amount_yuan']:.2f}元、盈利{e['positive_amount_yuan']:.2f}元，188个亏损、201个盈利事件；三日分母：亏损{n['negative_amount_yuan']:.2f}元、盈利{n['positive_amount_yuan']:.2f}元。这些事件可互相重叠，金额不能相加成一个账户结果。全434事件状态计数为{event['all_event_status_counts']}。", '',
              'BPF的三日事件筛选同时优于BP，但真实账户收益反而低24.0553个百分点：资金占用、许可触发后的入退顺序及复利路径改变，说明单独事件筛选不等于账户决策增量。没有把原账本中不利交易删除来构造伪反事实。', '',
              '同一旧323事件上的历史四折桥接见[EX048](../EX048_20261024/report.md)：新日程B→BF三日亏损识别32.6205%→45.2517%，但盈利遗漏33.7252%→39.9518%；旧四折的双向改善未复现。323与389的分母不能混用。', '',
              '## 年度与实际持仓说明', '',
              '| 配置 | 年度 | 继承资金净收益 | 年内回撤 | 日末平均持仓比例（全434日） |',
              '| --- | --- | ---: | ---: | ---: |']
    for item in diagnostics['accounts']:
        if item['window'] != 'full':
            continue
        for year in item['years']:
            lines.append(f"| {item['candidate_id']} | {year['year']} | {100*year['net_return']:.3f}% | {100*year['dd']:.3f}% | {100*item['average_close_exposure']:.3f}% |")
    lines += ['', '年度以此前账户权益和持仓连续承接，年内回撤用年初权益为局部起点；不是另起10万元，不作为新增年度硬门。预测许可撞上既有意图的日期数、实际多次买入和全部直接对照见[账户诊断](others/account_diagnostics.json)，这些占用日期不是可直接领取的盈利机会。', '',
              '## 核验、证据与收口', '',
              '训练：20个发布日期、140次拟合（U重复B的20次，无独立新信息；120个唯一家族/延迟/日期模型），3038预测与3038物理前缀重放独立通过。运行时价格/份额特征从实际绑定数据重算；14账户、5943决策、70账本、56项输入核对、14项SE回放审计通过。首配置串行与并行的两窗口五账本及结果哈希相同。正式14场景、技术重复2场景，不合计成16个独立配置。', '',
              '正式账户初次认证暴露平台Decimal周期成本与浮点费用的约1e−14元误拒，已由DEV在原批准实现范围修复，提交39e662d0，19项聚焦测试通过。保留[原始失败](others/audit_platform_initial_failure.json)及[技术说明](others/technical_notes.json)；策略参数、输入、账户及已发布身份未改变，不用重新运行获得更有利结果。完整账户损益诊断的动态分配分解仍为UNSUPPORTED，独立会计核验与SE数值审计不冒称该能力已支持。', '',
              '阶段二结论：支持T−1下份额辅助量价筛选、路径在份额背景下的条件性增量；保留相反背景和T−3反证，不宣称普遍有效、可靠预测入场亏损或已找到达标策略。P3暂不触发：聚合持有损益随原型改变，没有提供一个新的、当时可观察的持有状态与增量标签证据；重复原退出域已由EX043—047检验，不为填满路线再做相近枚举。后续若推进，主要问题是整体机会/资金占用/持有价值的结构协同，属于阶段三，需用户批准。', '',
              '全体数据已经用于多轮选择；两个窗口高度重叠，没有新独立样本。历史PIT、外推和重复选择限制继续保留。实验报告与阶段交付分别发布，旧候选资格不恢复。证据入口：[事前模型协议](protocols/plan.json)、[账户协议](protocols/accounts.json)、[全部账户](others/results.json)、[事件分母](others/event_metrics.json)、[独立账户审计](others/account_audit.json)、[发布引用](others/published_refs.json)。']
    (HERE / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    assert not (HERE / 'others/published_refs.json').exists()
    report()
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))
    ex = ExperimentRef('S015', HERE.name)
    materials = {}; refs = []
    for index in ('training_refs.json', 'account_refs.json'):
        for name, value in read(HERE / 'others' / index).items():
            ref = EvidenceRef.from_dict(value)
            assert ref.resolve(ROOT).read_bytes() == (HERE / name).read_bytes(), name
    for folder in ('src', 'protocols', 'others'):
        for path in sorted((HERE / folder).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix not in ('.py', '.json', '.csv', '.md'):
                continue
            if path.name.startswith('serial_') or path.name == 'progress.json' or (path.suffix == '.csv' and path.name.startswith('C49')):
                continue  # Full raw ledgers already reside inside formal account evidence.
            ref = publish_evidence(ctx, MaterialEvidenceWrite(ex, path.stem, path.read_bytes(), {'.py': 'text/x-python', '.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown'}[path.suffix], path.suffix[1:]))
            materials[path.relative_to(HERE).as_posix()] = ref.to_dict(); refs.append(ref)
    result = read(HERE / 'others/results.json')
    accounts = [EvidenceRef.from_dict(row['evidence']) for row in result['rows']]
    refs += accounts
    refs += [EvidenceRef.from_dict(read(HERE / 'others/serial_preflight_ref.json'))]
    refs += [EvidenceRef.from_dict(v) for v in read(HERE / 'protocols/plan.json')['sources'].values()]
    published = publish_evidence(ctx, ExperimentReportWrite(ex, sha256((HERE / 'report.md').read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, tuple(dict.fromkeys(refs))))
    validation = validate_experiment(RepositoryContext.discover(ROOT), ExperimentValidationRequest(ex, ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS', validation.issues
    save(HERE / 'others/published_refs.json', {'report': published.to_dict(), 'materials': materials,
        'evaluation_refs': [r.to_dict() for r in accounts], 'validation': validation.to_dict()})
    print('EX049_REPORT_PUBLICATION_PASS', flush=True)


if __name__ == '__main__':
    main()
