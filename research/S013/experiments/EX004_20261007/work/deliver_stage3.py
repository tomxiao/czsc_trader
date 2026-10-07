"""Publish the researcher's completed stage-three findings and selected ledgers."""
from dataclasses import replace
import importlib.metadata
import json
from strategy_runtime import StrategyInputBinding
from strategy_manager import CandidateKey
from czsc_trader.application import (
    publish_evidence, register_candidate, load_candidate, CandidateRegistrationRequest,
    assemble_delivery, validate_delivery,
)
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite, EvidenceRef
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT, WORK, DEPENDENCIES, context, candidate, request, cache_read, save
from economics import summarize


def main():
    research = context()
    experiment = ExperimentRef('S013', 'EX004_20261007')
    rows = json.loads((WORK / 'search_results.json').read_text(encoding='utf-8'))['rows']
    valid = [r for r in rows if r['status'] == 'SUCCEEDED']
    analysis = json.loads((WORK / 'search_analysis.json').read_text(encoding='utf-8'))
    quality = json.loads((WORK / 'quality_impact.json').read_text(encoding='utf-8'))
    stopping = (WORK / 'stopping_review.md').read_text(encoding='utf-8')
    assert analysis['matched_old_unique_configurations'] == 270
    assert analysis['unique_successful_configurations'] == quality['successful_configurations']
    assert quality['potential_economic_change_count'] == 0
    comparisons = json.loads((WORK / 'all_replay_comparisons.json').read_text(encoding='utf-8'))
    assert comparisons['status'] == 'COMPLETE' and len(comparisons['comparisons']) == 270
    refs = {}

    def material(name, filename, media='application/json'):
        path = WORK / filename
        ref = publish_evidence(research, MaterialEvidenceWrite(
            experiment, name, path.read_bytes(), media, path.suffix[1:]))
        refs[name] = ref
        return ref

    material('hfq-search-results', 'search_results.json')
    material('hfq-search-analysis', 'search_analysis.json')
    material('hfq-quality-impact', 'quality_impact.json')
    material('hfq-stopping-review', 'stopping_review.md', 'text/markdown')
    material('hfq-replay-plan', 'replay_plan.json')
    material('hfq-replay-coverage', 'all_replay_comparisons.json')
    material('hfq-replay-interruption-history', 'old_configuration_hfq_replay_comparisons.json')
    material('hfq-explicit-replay-completion-plan', 'replay_completion_plan.json')
    material('hfq-explicit-replay-completion-coverage', 'hfq_replay_completion_comparisons.json')
    material('hfq-parallel-interruption', 'parallel_interruption.json')
    material('hfq-parallel-interruption-r2', 'parallel_interruption_r2.json')
    material('hfq-explicit-recovery4-plan', 'replay_recovery4_plan.json')
    material('hfq-explicit-recovery4-coverage', 'hfq_replay_recovery4_comparisons.json')
    material('hfq-extended-preparation-rejection', 'extended_preparation_failure.json')
    save('audit_contract_correction.json', {
        'observed_operation': 'register_candidate(C0001)',
        'original_account_reference': json.loads((WORK / 'initial_account_reference.json').read_text(encoding='utf-8')),
        'original_audit_reason_codes': ['ORDER_LIMIT_MISMATCH', 'INVALID_FILL_TRIGGER'],
        'cause': '独立审计遗漏原始报价网格和T日归一化价格尺度，按固定研究价格网格核验限价',
        'correction_commit': '3a8ab3a7', 'focused_nodes_passed': 57,
        'effect': '保留旧证据；从相同缓存账本重新表达审计证据，不改实际请求、信号、成交、费用、权益和结果哈希',
    })
    material('hfq-audit-contract-correction', 'audit_contract_correction.json')
    for path in sorted(WORK.glob('*followup*plan.json')):
        material(path.stem.replace('_', '-'), path.name)
        compared = path.stem.replace('_plan', '_comparisons') + '.json'
        value = json.loads((WORK / compared).read_text(encoding='utf-8'))
        assert value['status'] == 'COMPLETE'
        material(path.stem.replace('_plan', '-coverage').replace('_', '-'), compared)
    for name in ('authorization', 'protocol'):
        refs[name] = EvidenceRef.from_dict(json.loads((WORK / f'{name}_reference.json').read_text(encoding='utf-8')))
    source = {p: (WORK / p).read_text(encoding='utf-8') for p in (
        'strategy_runtime/strategies/range_reversion.py', 'common.py', 'economics.py',
        'fixed_search.py', 'quality_audit.py', 'analyse_search.py', 'select_frontier.py',
        'prepare_completion.py', 'finish_replay.py', 'prepare_followup.py',
        'prepare_followup2.py', 'prepare_followup3.py', 'prepare_followup4.py', 'deliver_stage3.py',
        'extended_window/strategy_runtime/strategies/range_reversion.py')}
    save('reproduction_sources.json', {'files': source,
        'installed_versions': {name: importlib.metadata.version(name) for name in (
            'numpy', 'pandas', 'optuna', 'czsc-strategy-runtime')},
        'platform_commit': '9caede79', 'focused_test_nodes_passed': 95,
        'audit_correction_commit': '3a8ab3a7', 'audit_correction_focused_nodes_passed': 57,
        'test_count_note': '两批节点存在重叠，不求和',
        'full_regression': '本轮未请求、未执行',
        'resources': {'initial_max_workers': 8, 'recovery_and_followup_workers': 4,
                      'native_threads': 1, 'request_workers': 1},
        'data_retention': '保留research/S013/data/及候选登记记录；Git不包含DFLS资产',
    })
    material('hfq-reproduction-sources', 'reproduction_sources.json')
    if (WORK / 'performance_frequency.png').exists():
        material('hfq-performance-frequency', 'performance_frequency.png', 'image/png')

    first, baseline = cache_read(ROOT / '.tmp/s013-stage3-hfq/precheck.pkl.gz')
    entries, selected_refs, registration_records, selected_diagnostics = [], {}, [], {}
    chosen = [r for r in valid if r['candidate_id'] in analysis['retained_frontier_and_controls']]
    for row in chosen:
        identifier = row['candidate_id']
        number = int(identifier[1:])
        result = baseline if identifier == 'C0001' else cache_read(ROOT / f'.tmp/s013-stage3-hfq/{identifier}.pkl.gz')
        recalculated = summarize(result)
        for key in ('net_cagr', 'closed_trades', 'min_dd_margin', 'qualified', 'result_hash'):
            assert recalculated[key] == row[key]
        bound = replace(request(number, row['parameters'], first.execution_data), input_bindings={
            run.window_id: StrategyInputBinding.from_mapping(run.signals.support_data['input_binding'])
            for run in result.runs})
        ref = publish_evidence(research, EvaluationEvidenceWrite(
            experiment, f'hfq-account-{identifier.lower()}-audited', bound, result))
        selected_refs[identifier] = ref
        registration = register_candidate(research.repository, CandidateRegistrationRequest(
            candidate(number, row['parameters']), experiment, (ref,), DEPENDENCIES))
        loaded = load_candidate(research.repository, CandidateKey('S013', identifier))
        assert dict(loaded.payload) == dict(bound.strategy.payload)
        assert registration.content_sha256 == row['content_sha256']
        registration_records.append(registration.to_dict())
        ledger = result.runs[0].execution.account_daily
        fills = result.runs[0].execution.fills
        selected_diagnostics[identifier] = {'holding_session_fraction': float(ledger.quantity.gt(0).mean()),
            'total_fees': row['total_fees'], 'full_max_drawdown': row['full_max_drawdown'],
            'buy_fill_count': int(fills.side.eq('BUY').sum()),
            'sell_fill_count': int(fills.side.eq('SELL').sum()),
            'unfilled_orders': row['order_statuses'].get('UNFILLED', 0)}
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(registration.key, registration.content_sha256),
            '低区间位置捕捉反转；20日收益一阶相关性、动量、持有期限及损失控制用于确认与退出，T日可用信息在T+1执行。',
            '三项目标同时通过，建议进入阶段四自检' if row['qualified'] else
            '未达标前沿或反证：' + '、'.join(k for k, passed in row['gates'].items() if not passed),
            (d.EvaluationEvidenceRef(ref),)))
    save('selected_account_references.json', {key: value.to_dict() for key, value in selected_refs.items()})
    save('selected_registrations.json', {'registrations': registration_records})
    save('selected_account_diagnostics.json', selected_diagnostics)
    material('hfq-selected-account-diagnostics', 'selected_account_diagnostics.json')

    qualified = [r for r in valid if r['qualified']]
    bh = rows[0]['buyhold_cagr']
    threshold = rows[0]['return_threshold']
    conclusion = (f'{len(qualified)}个配置同时通过三项目标，建议进入阶段四自检。' if qualified else
                  '当前完整账户搜索未发现同时达标配置；建议依据停止评审决定继续研究或回退阶段二。')
    lines = ['# S013阶段三：后复权研究账户结果', '', conclusion, '',
        f"本轮成功评价{len(valid)}个独立配置，实际评价尝试{len(rows)}次；其中固定重算旧搜索270个独立配置。净年化门槛为{threshold:.4%}（1.5×同窗BuyHold {bh:.4%}），逐自然年回撤须严格更小，1636日须至少110笔闭合交易。三项同时核验，未降低目标。", '',
        '## 口径与平台交付', '',
        '采用用户选择的方案A：100表示100个研究单位。2019-12-31固定归一化锚点，因子0.2803；成交价格、现金、费用、持仓及BuyHold共用同一账户单位。研究单位包含供应商复权处理所对应的权益影响，不重复增加现金派息。PTE始终输出未复权价格和真实ETF份额。', '',
        '平台价格契约已本地提交9caede79，95个聚焦测试节点通过；候选登记暴露的独立审计价格尺度遗漏另以3a8ab3a7补齐，57个相关节点通过（两批节点有重叠），修改文件Ruff通过。本轮未执行全仓回归。尚未合并master、打tag、推送、同步或部署。研究模型的收益不直接等于真实整份额PTE账户收益。', '',
        '旧基线账户证据保持原件。此次审计修正为每日证据补充原始收盘与研究价格尺度，在原始网格核验参考限价，再按T日尺度转换；从相同缓存结果重新发布审计证据，不改请求、成交账本或经济结果哈希。正式登记的全部14个候选通过完整审计和加载核验。', '',
        '基线限价依据T日未复权收盘参考加20bp，在原始0.001报价网格取整后按T日因子转换；后续溢价对照采用实验前发布的参数计划，用户确认的限价买入约束保持。T+1使用同口径历史行情撮合，卖出市价，计划形成不读取下一日开盘或复权因子。旧协议中的“下一日开盘加20bp”文字与实际实现不一致，本轮明示修正，旧证据原件保留。', '',
        '持有期限与损失控制锚点按信号目标仓位序列计算；限价入场延后时，实际持有天数与成交成本会有差异。完整账本采用实际成交，不把信号次数当成闭合交易次数。', '',
        '### 口径修正的经济影响', '',
        '| 指标 | 原始价格口径 | 后复权研究口径 |', '| --- | ---: | ---: |']
    for key, label in (('net_cagr', '同一基线策略净年化'), ('buyhold_cagr', 'BuyHold净年化'),
                       ('return_threshold', '1.5倍收益门槛')):
        values = analysis['baseline_price_change'][key]
        lines.append(f"| {label} | {values['raw']:.4%} | {values['hfq']:.4%} |")
    lines += ['', '基准的口径修正幅度大于基线策略，旧收益门槛不再适用。旧schema3账户原件保留，本轮采用含明确价格契约的schema4请求；旧统计只用于历史对照，达标判断使用新账户。', '',
        '## 前沿与反证', '',
        '下表保留逐年回撤通过集合中净年化/频率的非支配配置、全部达标配置，以及基线、最高收益和最小搜索缺口对照。频率在达标线处截断，达标后不偏好更高频率。这是阶段三的取舍展示，尚未进行阶段四自检或排序。', '',
        '| 配置 | 净年化 | 闭合交易 | 每60日 | 逐年回撤 | 未满足项 | 全账户证据 |',
        '| --- | ---: | ---: | ---: | --- | --- | --- |']
    for row in sorted(chosen, key=lambda r: -r['net_cagr']):
        reasons = '、'.join({'return': '收益', 'annual_drawdown': '逐年回撤', 'frequency': '频率'}[k]
                           for k, passed in row['gates'].items() if not passed) or '无'
        ref = selected_refs[row['candidate_id']]
        lines.append(f"| {row['candidate_id']} | {row['net_cagr']:.4%} | {row['closed_trades']} | {row['frequency60']:.3f} | {'通过' if row['gates']['annual_drawdown'] else '未通过'} | {reasons} | [账本]({ref.path}) |")
    lines += ['', '### 全部达标候选的交易机制', '',
        '共同参数：180日高低区间，收盘价区间位置≤0.675时目标满仓；最长信号持有8个交易日；无相关性、动量或移动止损过滤，冷却期0。区间位置达到退出阈值、达到持有期限或触发已启用的信号锚点止损时目标清仓。买入限价按T日原始收盘与下表溢价形成，卖出市价；成交金额每侧费用仍为10bp。', '',
        '| 配置 | 退出区间位置 | 限价溢价 | 信号锚点止损 | 最小逐年回撤优势 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for row in qualified:
        p = row['parameters']
        stop = '未启用' if p['stop_loss'] is None else f"{p['stop_loss']:.0%}"
        lines.append(f"| {row['candidate_id']} | {p['exit']:.2f} | {p['limit_premium']:.2%} | {stop} | {row['min_dd_margin'] * 100:.4f}个百分点 |")
    if 'hfq-performance-frequency' in refs:
        lines += ['', f"![净年化与闭合交易取舍]({refs['hfq-performance-frequency'].path})"]
    dd_best = max((r for r in valid if r['gates']['annual_drawdown']), key=lambda r: r['net_cagr'])
    freq_dd = [r for r in valid if r['gates']['frequency'] and r['gates']['annual_drawdown']]
    annual_control = max(freq_dd, key=lambda r: r['net_cagr']) if freq_dd else dd_best
    lines += ['', '## 逐年回撤核验', '',
        f"展示逐年回撤通过集合中收益最高的{dd_best['candidate_id']}（频率未通过），以及全部达标集合中收益最高的{annual_control['candidate_id']}。每年从初始资金或上一年末权益开始取峰值，现金和持仓跨年连续；2026年截至9月30日。", '',
        f"| 年份 | BuyHold回撤幅度 | {dd_best['candidate_id']}（频率未达标） | {annual_control['candidate_id']}（全部达标） |", '| --- | ---: | ---: | ---: |']
    for year in dd_best['annual']:
        lines.append(f"| {year} | {dd_best['buyhold_annual'][year]['max_drawdown_magnitude']:.4%} | {dd_best['annual'][year]['max_drawdown_magnitude']:.4%} | {annual_control['annual'][year]['max_drawdown_magnitude']:.4%} |")
    lines += ['', '## 搜索与选择历史', '',
        '旧实验EX003保持原位。本轮在EX004先固定重算旧成功配置，再依新账本选择局部扩边与反证；旧原始价格排名和阈值未参与新达标判定。Optuna管理固定队列，种子13；最多8个spawn进程，每个1个原生线程，单请求workers=1。固定队列中的重复配置复用同口径结果，失败状态显式保存。', '',
        f"本轮两次Windows spawn管道句柄失效，保留{len(rows) - len(valid)}项UNKNOWN原状态和失败trial；新计划显式重试并补齐剩余未执行项，成功后逐配置核对完整覆盖。第二次中断后明确调整为4个工作进程，每个父进程仅发起一批，继续多进程完整评价。未知状态未计作成功，也未作为策略失败。", '',
        '| 搜索组 | 实际评价 | 独立配置 | 达标 |', '| --- | ---: | ---: | ---: |']
    for name, group in analysis['groups'].items():
        lines.append(f"| {name} | {group['evaluations']} | {group['unique_configurations']} | {group['qualified']} |")
    lines += ['', '完整参数、指标、年度账本核验值、对应身份及原始/后复权同配置对照见关联搜索证据。已保留全部达标配置；其余正式保留点覆盖已声明前沿和重要反证，其完整账户及源码可公开加载。', '',
        '## 数据与结论边界', '',
        f"当前检查覆盖{quality['successful_configurations']}个成功配置。四处High偏差未进入本策略买入LIMIT/卖出MARKET的撮合输入；2020-12-01的Low偏差未发现会改变成交金额的订单（潜在改变数量{quality['potential_economic_change_count']}）。保留原异常和核对证据，没有手工改写行情。", '',
        '全部开发池用于研究和参数选择，逐年比较属于用户回撤约束，不能解释为独立样本外验证。组件与旧搜索结果已见，供应商复权因子历史发布时间、修订及实盘馈送延迟未重建。采用当前历史版本的复权研究模型；后续真实份额交易仍须单独评价。', '',
        '## 停止评审与下一步', '', stopping.strip(), '', '## 关联证据', '']
    for name, ref in refs.items():
        lines.append(f'- [{name}]({ref.path})')
    report = '\n'.join(lines) + '\n'
    searches = tuple(d.SearchSummary(name,
        '基线完整账户单次评价' if name == 'hfq_initial' else 'Optuna管理固定队列和同配置去重',
        '510500.SH开发池2020-01-01至2026-09-30；HFQ_RESEARCH，100个研究单位',
        group['evaluations'], group['unique_configurations'],
        '三项目标同时核验；保留全部达标配置及已声明前沿与反证',
        ('全开发池复用；存在选择偏差，无独立保留样本',),
        (refs['hfq-search-results'], refs['hfq-search-analysis'])) for name, group in analysis['groups'].items())
    payload = d.CandidateSet(tuple(entries), tuple(CandidateKey('S013', r['candidate_id']) for r in qualified),
                             searches, conclusion)
    facts = (d.FactValue('qualified_count', len(qualified), '个配置', d.FactStatus.AVAILABLE,
                         (refs['hfq-search-results'],)),)
    predecessors = tuple(d.DeliveryReference.from_dict(json.loads(path.read_text(encoding='utf-8'))) for path in (
        WORK / 'mandate_reference.json', ROOT / 'research/S013/materials/stage2_components_reference_20261007.json'))
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 1, predecessors),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, facts, (), report=report,
                          evidence=tuple(dict.fromkeys(refs.values()))))
    checked = validate_delivery(research.repository, receipt.reference)
    assert checked.status == d.ValidationStatus.PASS, checked.to_dict()
    save('stage3_reference.json', receipt.reference.to_dict())
    save('stage3_validation.json', checked.to_dict())
    print(json.dumps({'delivery': receipt.reference.to_dict(), 'validation': checked.to_dict(),
                      'qualified': len(qualified), 'retained': len(chosen)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
