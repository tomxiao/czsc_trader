"""Report and publish the six fixed EX042 prototypes, without candidate handoff."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_experiment
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest,
    ExperimentValidationScope)

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
EX = ExperimentRef('S015', HERE.name)
AUDITS = ('training_audit.json', 'runtime_checks.json', 'account_audit.json')
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

def inputs():
    result = read(HERE / 'others/results.json')
    rows = result['rows']
    assert len(rows) == 6 and len({row['candidate_id'] for row in rows}) == 6
    assert result['new_configurations'] == 6 and result['account_scenarios'] == 12
    assert result['technical_precheck_extra_scenarios'] == 2 and result['precheck_five_ledgers_equal'] is True
    identities = {('A', 'path'), ('A', 'risk'), ('A', 'and'), ('B', 'path'), ('B', 'risk'), ('B', 'and')}
    assert {(row['parameters']['family'], row['parameters']['mode']) for row in rows} == identities
    for row in rows:
        assert row['parameters']['hold'] == 3 and row['parameters']['exposure'] == 1.0
        full, common = row['runs']['full'], row['runs']['s011_common']
        assert full['center_pass'] == all(full['checks'].values())
        assert common['return_superior'] == (common['net_return'] > RETURN_GATE)
        assert common['dd_superior'] == (common['dd'] < DD_GATE)
        assert common['dual_pass'] == (common['return_superior'] and common['dd_superior'])
        assert row['both_center_pass'] == (full['center_pass'] and common['dual_pass'])
        assert full['net_return'] == common['net_return'] and full['dd'] == common['dd']
        ref = EvidenceRef.from_dict(row['evidence'])
        assert ref.experiment == EX and ref.schema == 'account_evaluation' and ref.schema_version == 7
        ref.resolve(ROOT)
    assert sum(row['both_center_pass'] for row in rows) == result['qualified_centers'] == 0
    summary = read(HERE / 'others/training_summary.json')
    assert summary['first_release'] == '2025-02-27' and summary['releases'] == 20 and summary['fitted_models'] == 80
    states = {name: read(HERE / 'others' / name) if (HERE / 'others' / name).exists() else None for name in AUDITS}
    return result, summary, states

def report():
    assert not (HERE / 'others/published_refs.json').exists(), 'Published experiment report is immutable'
    result, training, audits = inputs()
    complete = all(value is not None and value.get('status') == 'PASS' for value in audits.values())
    rows = result['rows']; benchmark = rows[0]['runs']['full']
    lines = ['# S015 路径与风险组件的六组固定账户原型', '',
             'Status: ' + ('COMPLETED' if complete else 'IN_PROGRESS'), '',
             '六组固定原型已完成12个正式窗口场景，434日原中心门通过0/6，415日严格双目标通过0/6，联合中心通过0/6。本实验尚非本轮阶段三最终收尾；当前新增合格候选为0，没有登记或交接候选集，也未执行阶段四32点扰动与费用压力。', '',
             '用户已授权阶段三。全部配置在计算前固定：A/B两套模型，各比较收益许可path、风险许可risk、二者交集and，意图持续3日、初始资金使用比例100%。Optuna仅排队记录这6个固定配置，没有按本轮成绩寻优阈值、仓位或持续天数。后续有依据的构造问题由独立后继实验处理，不覆盖本轮失败结果。', '',
             '## 六组实际连续账户', '',
             '434日为2025-01-02至2026-10-21，415日为2025-02-06至2026-10-21；各自独立10万元、空仓初始化。下表净收益为连续账户扣费后的完整区间收益，回撤包含初始资金。费用为434日实际双侧费用合计。', '',
             '| 原型 | 模型/许可 | 434日净收益 | 434日年化 | 最大回撤 | 415日净收益 | 415日回撤 | 闭合周期 | 60日频率中位 | ≥3笔窗口 | 费用（元） |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        p = row['parameters']; f, c = row['runs']['full'], row['runs']['s011_common']
        lines.append(f"| {row['candidate_id']} | {p['family']}/{p['mode']} | {100*f['net_return']:.3f}% | {100*f['cagr']:.3f}% | {100*f['dd']:.3f}% | {100*c['net_return']:.3f}% | {100*c['dd']:.3f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']}/{f['frequency_windows']} | {f['fees']:.2f} |")
    lines += ['', '训练在积累至少30个已成熟标签后才首次生成模型：首次生效2025-02-27，开发池位置34。此前34个开发交易日持有现金；415日窗口也在首次模型出现前开始。两窗使用同一条按开发池日期生成的学习时间线和相同10万元，因而六组各自后续交易路径相同，净收益和回撤完全相同。年化分母、频率窗口和净值序列长度仍不同；这不是把434日账户切片继承持仓，也不应把两窗当两份独立验证证据。', '',
              '## 原目标逐项核对', '',
              f"434日可执行LimitBuyHold基准年化{100*benchmark['benchmark_cagr']:.6f}%、回撤{100*benchmark['benchmark_dd']:.6f}%。本池中心年化至少{150*benchmark['benchmark_cagr']:.6f}%，回撤同时不超过{80*benchmark['benchmark_dd']:.6f}%及25%；60日闭合交易中位至少6笔，375个完整窗口至少338个有3笔。", '',
              '| 原型 | 434日未通过项 | 434日中心门 | 415收益严格优于S011 | 415回撤严格小于S011 | 联合中心 |',
              '| --- | --- | --- | --- | --- | --- |']
    for row in rows:
        f, c = row['runs']['full'], row['runs']['s011_common']
        failed = '、'.join(CHECK_NAMES[key] for key, passed in f['checks'].items() if not passed) or '无'
        yes = lambda value: '通过' if value else '未通过'
        lines.append(f"| {row['candidate_id']} | {failed} | {yes(f['center_pass'])} | {yes(c['return_superior'])} | {yes(c['dd_superior'])} | {yes(row['both_center_pass'])} |")
    lines += ['', f'415日只检验固定S011基线的两项严格门：净收益>{100*RETURN_GATE:.9f}%，最大回撤幅度<{100*DD_GATE:.9f}%，按未取整原值比较，相等不通过。结果JSON中415日同时保存的普通基准检查仅供诊断，不能将它们当作新增415日验收要求。上述联合中心仍不等于完整默认资格：32点扰动和费用压力本实验未执行。', '',
              'B/path有最高净收益53.928%，但回撤33.102%，原相对和绝对回撤均未过；它也未满足415日两项门。A/risk净收益18.693%、回撤24.179%，原收益门失败。B/and回撤最低16.096%，仍明显高于S011的7.249%，且原频率中位只有5笔。不能从单一改善指标挑选“合格策略”。', '',
              '## 纯价格表达、旧控制与阶段二落差', '',
              'A的预测模型仅用4个价格路径表达或4个波动转换表达；B在同样表达前加过去1/5日收益、20日波动/振幅和当日量价压力。两套都遵守同一交易规则。运行时统一计算13个特征以核对输入，A模型不使用旧控制列。名称或输入不同，尚不能证明与S011的经济行为独立。', '',
              '阶段二统计的是每次重新投入10万元、可相互重叠的独立事件；本轮同一资金账户会排斥重叠机会、按已有仓位和现金决定数量，并支付实际重复交易费用。阶段二四折主要覆盖位置100以后；本轮从位置34开始采用每20日更新的历史模型。训练日程、选择队列和成交路径均不同，不能把阶段二事件金额或平均收益直接搬成账户预期。', '',
              '本轮说明有限信息用途尚未兑现为满足目标的策略。单独risk与交集的优劣也发生变化，例如B/risk账户净收益为−15.992%，B/and为+16.181%；这不抹去阶段二的机会代价反证，也不是足以确证组合机制的新独立样本。', '',
              '## 意图周期与补买语义', '',
              '采用available_cash_fraction/entry_cycle，入场时按可用现金比例锁定周期目标数量，不进行每天按净资产比例重配。若目标数量尚未完成，在正目标意图持续期间可继续尝试买入；它不是只下一笔买单。hold=3是信号意图时钟：触发T后T/T+1/T+2保持正目标，T+3发退出意图，通常T+4执行卖出。周期内预测变差不提前退出，未成交天数仍消耗意图年龄，持有天数不一定等于3。', '',
              '| 原型 | BUY成交笔数 | 存在多次BUY的周期数 | 额外BUY成交数 |', '| --- | ---: | ---: | ---: |']
    for row in rows:
        fills = pd.read_csv(HERE / f"others/{row['candidate_id']}_full_fills.csv")
        buys = fills[fills.side.eq('BUY')]; sizes = buys.groupby('cycle_id').size()
        lines.append(f"| {row['candidate_id']} | {len(buys)} | {int((sizes>1).sum())} | {int((sizes-1).clip(lower=0).sum())} |")
    lines += ['', '周期内追加买入不另计闭合交易次数；末端未平仓不算闭合周期。此构造沿用1%限价、原tick/lot/涨跌幅保护和市场卖出、每侧0.1%费用、HFQ_RESEARCH与DAILY_RANGE_V3，不强制期末平仓。']
    account_audit = audits['account_audit.json']
    if account_audit is not None:
        lines += ['', '## 实际成交后的损益分解', '',
                  '| 原型 | 入场日毛收益（元） | 后续毛收益（元） | 实际费用（元） | 净收益（元） |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |']
        for item in account_audit['accounts']:
            if item['window'] == 'full':
                lines.append(f"| {item['candidate']} | {item['entry_day_gross_yuan']:.2f} | {item['later_gross_yuan']:.2f} | {item['fees_yuan']:.2f} | {item['net_yuan']:.2f} |")
        lines += ['', 'B/path的入场日毛收益67217.30元、之后毛收益9300.20元，实际费用22589.11元。收益较集中于入场日，提供了在独立后继协议中检验有限持有域的具体理由；不能由此保证缩短持有会提高收益或降低回撤。毛收益是固定已成交现金流加末端估值、扣费前的账本归因，不是免手续费重跑；入场日/后续拆分也不是可避免损失的因果估计。']
    differences_path = HERE / 'others/input_difference_observed.json'
    if differences_path.exists():
        difference = read(differences_path)
        volume = difference['differences']['Volume']
        lines += ['', '## 实际绑定输入与旧快照的差异', '',
                  f"实际绑定盘中数据与旧快照比较，{difference['rows']}行中Volume有{volume['changed']}行不同，最大绝对差{volume['max_abs']:.0f}、最大相对差{volume['max_rel']:.9g}。盘中OHLC、Amount及AvailableDate一致，日线实际使用字段一致；不能声称全字段或全部数据身份完全相同。",
                  '盘中Volume未用于这13个特征，执行亦未启用成交量容量约束；独立审计重建了实际绑定输入下的5094行特征、预测、许可及意图，均与已认证特征和冻结系数一致。因此本轮有针对实际使用信息的等价证据，差异原件及新旧身份仍完整保留，不扩展为其他用途无影响的结论。']
    lines += ['',
              '## 历史学习、技术检查与证据边界', '',
              f"共{training['releases']}个生效日期、{training['fitted_models']}个模型拟合（2家族×2职责×20期），固定Ridge正则10。这里的80指模型套数，不是只有80个标量系数。每次训练只允许实际标签已知日严格早于生效日；标准化和风险中位阈值由当时训练集计算。模型系数、标准化量和生效日期嵌入不可变候选参数，运行时只选当日已生效模型，不读取可变研究文件。", '',
              '这是截至2026-10-21的研究重放计划，不能称已实现部署后的自动训练更新。原历史数据版本及公告时点可得性仍有既有局限；所有样本已经研究，时间因果核验不证明独立预测有效性。', '',
              '主运行器记录首个配置先串行计算，再在正式并行中重算：两窗口的account_daily、decisions、orders、fills、trades五类账本逐值一致，result_hash一致。串行账本未单独持久化，独立账户审计没有另行复现此串并行比较；其范围是12个已保存正式场景。6个固定配置对应12个正式账户场景，另有2个技术重复场景；不能把技术重复当新配置或独立样本。计算最多4进程、每进程原生线程1。', '',
              '第一次prepare因runtime binding使用短ID C4200被公开接口拒绝，发生在数据绑定和账户执行之前：失败prepare调用1次、失败账户场景0。原冻结accounts.py未改，另行冻结binding_correction.json与run_accounts.py，只将绑定身份改为完整S015-C4200；未改变策略、模型、费用、窗口或6配置。', '',
              '| 核验 | 当前状态 |', '| --- | --- |']
    for name, audit in audits.items():
        lines.append(f"| {name} | {'待完成' if audit is None else audit.get('status', '未知')} |")
    lines += ['', '技术审计通过只确认实现、身份和数值可核验，不替代目标达标。下一步仅按已授权阶段三在独立后继协议中处理明确的构造问题；本实验不发布阶段三候选集，不更新研究族状态，不推进阶段四、冻结或PTE。', '',
              '证据：[事前计划](protocols/stage3_plan.json)、[账户配置](protocols/accounts.json)、[技术补充](protocols/binding_correction.json)、[全部账户结果](others/results.json)、[训练审计](others/training_audit.json)、[运行契约核验](others/runtime_checks.json)、[账户审计](others/account_audit.json)、[输入差异](others/input_difference_observed.json)。']
    (HERE / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print('EX042_REPORT_READY' if complete else 'EX042_REPORT_AWAITING_ACCOUNT_AUDIT', flush=True)

def publish():
    assert not (HERE / 'others/published_refs.json').exists(), 'Already published; never overwrite'
    result, _, audits = inputs()
    assert all(value is not None and value.get('status') == 'PASS' for value in audits.values()), 'All three audits must PASS'
    for audit in audits.values():
        for name, digest in audit.get('sha256', {}).items():
            path = HERE / name
            assert path.is_file() and sha256(path.read_bytes()).hexdigest() == digest, f'Audit-bound bytes changed: {name}'
    for filename in ('account_refs.json', 'training_refs.json', 'binding_correction_refs.json'):
        for name, payload in read(HERE / 'others' / filename).items():
            reference = EvidenceRef.from_dict(payload)
            assert reference.experiment.strategy_id == 'S015'
            relative = (('src/' if name.endswith('.py') else 'protocols/') + name
                        if filename == 'training_refs.json' else name)
            assert reference.resolve(ROOT).read_bytes() == (HERE / relative).read_bytes(), f'Frozen source changed: {relative}'
    report()
    files = sorted(path for folder in ('src', 'protocols', 'others') for path in (HERE / folder).rglob('*')
                   if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.json', '.csv', '.md')
                   and path.name != 'published_refs.json')
    refs = [EvidenceRef.from_dict(row['evidence']) for row in result['rows']]
    for path in files:
        if path.suffix == '.json':
            for reference in evidence_refs(read(path)):
                assert reference.experiment.strategy_id == 'S015', 'Only S015 source evidence authorized'
                reference.resolve(ROOT); refs.append(reference)
    repository = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repository, ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))
    media = {'.py': 'text/x-python', '.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown'}
    materials = {}
    for path in files:
        reference = publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(), media[path.suffix], path.suffix[1:]))
        materials[path.relative_to(HERE).as_posix()] = reference.to_dict(); refs.append(reference)
    published = publish_evidence(ctx, ExperimentReportWrite(EX, sha256((HERE / 'report.md').read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, tuple(dict.fromkeys(refs))))
    validation = validate_experiment(repository, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS', validation.issues
    save(HERE / 'others/published_refs.json', {'report': published.to_dict(), 'materials': materials,
          'evaluation_refs': [row['evidence'] for row in result['rows']], 'validation': validation.to_dict()})
    print('EX042_PUBLISHED', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=('report', 'publish'))
    {'report': report, 'publish': publish}[parser.parse_args().mode]()
