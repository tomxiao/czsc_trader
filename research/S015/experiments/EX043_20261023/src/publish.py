"""Report and publish the fixed holding-domain experiment; no candidate handoff."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_experiment
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest,
    ExperimentValidationScope)

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
PREV = HERE.parent / 'EX042_20261023'
EX = ExperimentRef('S015', HERE.name)
RETURN_GATE = 0.9158029150000013
DD_GATE = 0.07248663749114126
CHECK_NAMES = {'return': '年化收益', 'relative_drawdown': '相对回撤', 'absolute_drawdown': '绝对回撤',
               'frequency_median': '频率中位数', 'frequency_coverage': '频率覆盖'}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def evidence_refs(value):
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef':
            yield EvidenceRef.from_dict(value)
        else:
            for child in value.values():
                yield from evidence_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from evidence_refs(child)


def authenticate(mapping, directory):
    for relative, payload in mapping.items():
        reference = EvidenceRef.from_dict(payload)
        assert reference.experiment.strategy_id == 'S015'
        assert reference.resolve(ROOT).read_bytes() == (directory / relative).read_bytes(), relative


def inputs():
    result = read(HERE / 'others/results.json')
    protocol = read(HERE / 'protocols/accounts.json')
    authenticate(read(HERE / 'others/protocol_refs.json'), HERE)
    authenticate(protocol['dependencies'], PREV)
    authenticate(protocol['binding_correction'], PREV)
    prior = EvidenceRef.from_dict(protocol['reused_hold3'])
    assert prior.experiment == ExperimentRef('S015', PREV.name)
    prior_result = read(prior.resolve(ROOT))
    assert len(prior_result['rows']) == 6 and prior_result['qualified_centers'] == 0
    rows = result['rows']
    assert len(rows) == len({row['candidate_id'] for row in rows}) == 24
    assert [row['parameters'] for row in rows] == protocol['configurations']
    assert result['new_configurations'] == 24 and result['account_scenarios'] == 48
    assert result['technical_precheck_extra_scenarios'] == 0 and result['precheck_five_ledgers_equal'] is False
    for row in rows:
        full, common = row['runs']['full'], row['runs']['s011_common']
        assert full['center_pass'] == all(full['checks'].values())
        assert common['return_superior'] == (common['net_return'] > RETURN_GATE)
        assert common['dd_superior'] == (common['dd'] < DD_GATE)
        assert common['dual_pass'] == (common['return_superior'] and common['dd_superior'])
        assert row['both_center_pass'] == (full['center_pass'] and common['dual_pass'])
        assert full['net_return'] == common['net_return'] and full['dd'] == common['dd']
        reference = EvidenceRef.from_dict(row['evidence'])
        assert reference.experiment == EX and reference.schema == 'account_evaluation' and reference.schema_version == 7
        reference.resolve(ROOT)
    assert sum(row['runs']['full']['center_pass'] for row in rows) == 2
    assert sum(row['runs']['s011_common']['dual_pass'] for row in rows) == 0
    assert sum(row['both_center_pass'] for row in rows) == result['qualified_centers'] == 0
    audits = {'account_audit.json': read(HERE / 'others/account_audit.json')}
    for name in ('training_audit.json', 'runtime_checks.json'):
        reference = EvidenceRef.from_dict(protocol['dependencies']['others/' + name])
        audits[name] = read(reference.resolve(ROOT))
    assert all(audit['status'] == 'PASS' for audit in audits.values())
    audit = audits['account_audit.json']
    assert len(audit['accounts']) == 48 and audit['formal_ledger_exports_checked'] == 240
    assert audit['feature_prediction_intention_rows'] == 20376 and audit['input_checks_count'] == 144
    assert audit['canonical_window_equivalence'] == 'PASS'
    accounts = {(item['candidate'], item['window']): item for item in audit['accounts']}
    assert len(accounts) == 48
    for row in rows:
        for window, run in row['runs'].items():
            item = accounts[row['candidate_id'], window]
            assert item['parameters'] == row['parameters'] and item['ledger_reconciliation'] == 'PASS'
            for key in ('net_return', 'cagr', 'dd', 'closed', 'frequency_median', 'frequency_good', 'frequency_windows'):
                assert abs(item[key] - run[key]) < 1e-10, (row['candidate_id'], window, key)
    differences = read(HERE / 'others/input_difference_observed.json')
    assert len(differences['differences']) == 48
    return result, audits, differences


def report():
    assert not (HERE / 'others/published_refs.json').exists(), 'Published experiment report is immutable'
    result, audits, differences = inputs()
    rows = result['rows']; benchmark = rows[0]['runs']['full']
    lines = ['# S015 固定模型的持有域账户实验', '', 'Status: COMPLETED', '',
             '24个事前固定配置完成48个正式账户窗口场景，无新增技术重复账户。434日原中心门通过2/24，415日严格双目标通过0/24，联合中心通过0/24。本实验新增合格候选为0；尚非本轮阶段三最终交付，没有登记或交接候选，也没有执行阶段四32点扰动和费用压力。', '',
             '## 研究问题与冻结范围', '',
             'EX042的六个hold=3账户均失败，且B/path实际成交毛收益集中于入场日，形成信息有效期与固定持有时间是否匹配的具体问题。本轮同时保留缩短持有减少风险、延长持有减少费用两种解释：A/B两套模型×path/risk/and三种许可×hold=1、2、5、7，共24配置。hold=3只引用EX042原证据，不重复计算或计数。全部使用100%可用现金比例，无杠杆。', '',
             'A仅用价格路径或波动转换表达；B在对应表达前加入过去1/5日收益、20日波动/振幅及当日量价压力旧控制。path表示收益预测非负的入场许可，risk表示风险预测低于当时训练阈值的许可，and为同时满足。统一运行时计算13个特征，A模型不使用旧控制列。没有新增模型、数据、组件、许可阈值或止损规则。Optuna仅排队固定配置索引，记录全窗/共同窗净收益和回撤四目标。', '',
             '复用EX042的20个历史生效日期、80套模型拟合及其系数，本轮新增拟合0。30个成熟标签起训、每20日更新、Ridge正则10的原学习计划不变；标签可得日期必须严格早于生效日期，标准化与风险中位阈值均来自当时训练样本。这是历史研究重放，未实现部署后的自动训练更新。', '',
             '## 全部24个账户结果', '',
             '434日为2025-01-02至2026-10-21，415日为2025-02-06至2026-10-21，分别独立10万元、空仓开始。净收益已扣实际费用，最大回撤包括初始资金；费用、闭合周期和频率列为434日。所有失败配置完整保留。', '',
             '| 原型 | 模型/许可 | hold | 两窗净收益 | 两窗回撤 | 434日年化 | 闭合周期 | 60日频率中位 | ≥3笔窗口 | 费用（元） | 434日未通过项 |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in rows:
        p = row['parameters']; f = row['runs']['full']
        failed = '、'.join(CHECK_NAMES[key] for key, passed in f['checks'].items() if not passed) or '无（中心通过）'
        lines.append(f"| {row['candidate_id']} | {p['family']}/{p['mode']} | {p['hold']} | {100*f['net_return']:.3f}% | {100*f['dd']:.3f}% | {100*f['cagr']:.3f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']}/{f['frequency_windows']} | {f['fees']:.2f} | {failed} |")
    lines += ['',
              '首次模型生效为2025-02-27，即开发池位置34。此前34个开发交易日持有现金，415日窗口也在首次生效前开始。两窗使用同一按开发池日期生成的模型时间线和相同10万元，后续交易路径一致，因此每配置两窗净收益和回撤完全相同；年化分母、频率窗口及净值长度不同。两窗均重新初始化，未继承434日账户切片持仓，也不能作为两份独立验证样本。', '',
              '## 原目标与资格', '',
              f"434日可执行LimitBuyHold基准年化{100*benchmark['benchmark_cagr']:.6f}%、回撤{100*benchmark['benchmark_dd']:.6f}%。原中心门要求年化至少{150*benchmark['benchmark_cagr']:.6f}%，回撤同时不超过{80*benchmark['benchmark_dd']:.6f}%和25%；60日闭合交易中位至少6笔，375个完整窗口至少338个有3笔。", '',
              f'415日严格要求净收益>{100*RETURN_GATE:.9f}%且最大回撤幅度<{100*DD_GATE:.9f}%，依据未取整原值比较，相等不通过。24配置的415日收益门、回撤门分别均0通过，联合中心自然为0。结果JSON中的415日普通基准检查仅作诊断，不能当作新增验收要求。', '',
              'C4307（A/risk/7）净收益56.534%、回撤16.538%，C4311（A/and/7）净收益50.856%、回撤22.177%，仅通过434日原中心门。净收益最高者仍低于S011的91.580%；回撤最低的C4320（B/and/1）为11.441%，仍高于S011的7.249%，其净收益只有3.276%。收益改善不能补偿回撤不达标，原中心通过也不能代替两窗AND或完整默认资格。', '',
              '## 持有时间、成本与边界解释', '',
              '延长持有对A/risk的收益有帮助，但各家族并不单调：B/risk从hold=5到7收益反而下降，且交易频率不达标；缩短B/path至1日降低回撤，同时大幅减少相对EX042三日原型的收益。可支持“持有长度是有影响的构造变量”，不足以证明短持有或长持有普遍更优。and也没有表现出跨长度、跨模型的一致优势。', '',
              '事前协议将hold=7设为暂定上界：若有意义的收益/风险前沿在此改善，可在独立后继协议中检查hold=9及更长持有的最大交易频率可行性。本实验的两个原中心通过配置均落在7，支持按该边界规则作有限后继核验；不能将上界附近改善直接外推。仓位其他比例本轮未检验，协议中的简单缩放直觉不是其无效的数学证明，不扩大本实验结论。', '',
              '阶段二独立事件可重叠、每次重新投入10万元；本轮连续账户必须共享资金并排斥重叠机会，实际成交数量、复利与费用共同决定收益。阶段二四折与本轮位置34起的历史学习日程亦不同。事件诊断的均值或保留金额不能作为账户收益承诺；本轮明确否定这24种构造达到现有双窗目标。', '',
              '## 实际执行与账户审计', '',
              '沿用available_cash_fraction/entry_cycle：入场按可用现金比例锁定周期目标数量，正意图期间可重试未完成买入，不是每天按净资产比例调仓。hold是信号意图年龄，未成交日也消耗时钟；实际持仓间隔逐周期核对，不能强称一定等于hold。周期内补买不另算闭合交易，期末未平仓按末日收盘估值、不强制卖出。1%买入限价、原tick/lot与涨跌幅保护、市场卖出、每侧0.1%费用、HFQ_RESEARCH及DAILY_RANGE_V3保持不变。', '',
              '独立审计PASS：48个正式场景、240份五类账本、144份实际输入核对，以及20376行实际特征/预测/许可/意图逐行一致；冻结模型身份、锁定周期数量、持有间隔、闭合交易与频率、扣费净值和回撤均核对。审计未重新prepare或evaluate账户。所有入场/后续毛收益、费用和未成交/补买/期末持仓明细保留于account_audit.json与audit_cycle_details.csv。', '',
              '毛收益分解固定实际成交现金流并加入末端估值，属于扣费前账本归因，不是零手续费重跑；入场日/后续拆分不是可避免损失的因果估计。技术审计通过确认实现与数值可核验，不代表预测有效或研究目标通过。', '',
              'EX043没有新增串并行技术重复场景，precheck_five_ledgers_equal=false表示未重复执行，不表示比较失败。复用EX042运行路径的串并行技术预检；其主运行器记录两窗五账本一致，但串行账本未另行持久化，不能声称本轮独立审计再次复现了该比较。EX043最多4进程、每进程原生线程1，24个任务全部完成、失败0。', '',
              'EX042初次prepare曾因短ID被拒绝，后以冻结技术补充将绑定身份改为完整S015-C4200；失败发生在账户执行前。EX043直接复用已认证修正，不改模型、策略或窗口，也不将旧技术调用计成本轮新账户。', '',
              '## 未使用字段的差异披露', '']
    sample = differences['differences'][0]; volume = sample['unused_field_differences']['Volume']
    lines += [f"实际绑定盘中输入与旧认证快照相比，{sample['rows']}行中Volume有{volume['rows']}行不同，最大绝对差{volume['max_absolute']:.0f}，最大相对差{volume['max_relative']:.9g}。48个场景记录同一底层差异，不代表48组独立变化。盘中实际使用的OHLC、Amount及AvailableDate、日线实际使用字段均精确一致；不能宣称全字段或数据身份完全一致。", '',
              '盘中Volume未进入这13个特征，执行未启用成交量容量约束；20376行实际特征/预测/许可/意图均已独立核对。因此有针对本轮已使用信息的等价证据，原差异和身份完整保留，不延伸为其他用途无影响。', '',
              '## 发布边界与下一步', '',
              '账户审计、复用训练审计和运行契约核验均为PASS。报告发布只固化本次失败与有限构造证据；本脚本不组装CANDIDATES、不更改研究族状态、不发布ASSESSMENT、不执行阶段四或PTE。下一步建议按事前上界规则完成有限后继核验后，由阶段三统一交付全部结果；若仍无双窗合格中心，应如实以空交接集合收尾。', '',
              '证据：[冻结账户协议](protocols/accounts.json)、[全部结果](others/results.json)、[账户审计](others/account_audit.json)、[周期明细](others/audit_cycle_details.csv)、[输入差异](others/input_difference_observed.json)、[冻结引用](others/protocol_refs.json)。复用模型、训练与运行检查由账户协议中的EvidenceRef逐份认证。']
    (HERE / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print('EX043_REPORT_READY', flush=True)


def publish():
    assert not (HERE / 'others/published_refs.json').exists(), 'Already published; never overwrite'
    result, _, _ = inputs()
    report()
    files = sorted(path for folder in ('src', 'protocols', 'others') for path in (HERE / folder).rglob('*')
                   if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.json', '.csv', '.md')
                   and path.name != 'published_refs.json')
    refs = [EvidenceRef.from_dict(row['evidence']) for row in result['rows']]
    for path in files:
        if path.suffix == '.json':
            for reference in evidence_refs(read(path)):
                assert reference.experiment.strategy_id == 'S015'
                reference.resolve(ROOT)
                refs.append(reference)
    repository = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repository, ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))
    media = {'.py': 'text/x-python', '.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown'}
    materials = {}
    for path in files:
        reference = publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(), media[path.suffix], path.suffix[1:]))
        materials[path.relative_to(HERE).as_posix()] = reference.to_dict()
        refs.append(reference)
    published = publish_evidence(ctx, ExperimentReportWrite(EX, sha256((HERE / 'report.md').read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, tuple(dict.fromkeys(refs))))
    validation = validate_experiment(repository, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS', validation.issues
    save(HERE / 'others/published_refs.json', {'report': published.to_dict(), 'materials': materials,
          'evaluation_refs': [row['evidence'] for row in result['rows']], 'validation': validation.to_dict()})
    print('EX043_PUBLISHED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('report', 'publish'))
    {'report': report, 'publish': publish}[parser.parse_args().mode]()
