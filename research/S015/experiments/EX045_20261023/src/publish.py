"""Report and publish the fixed prospective account experiment; no candidate handoff."""
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
    for reference in evidence_refs(protocol):
        assert reference.experiment.strategy_id == 'S015'
        reference.resolve(ROOT)
    rows = result['rows']
    assert len(rows) == len({row['candidate_id'] for row in rows}) == 12
    assert [row['parameters'] for row in rows] == protocol['configurations']
    assert result['new_configurations'] == 12 and result['account_scenarios'] == 24
    assert result['technical_precheck_extra_scenarios'] == 2 and result['precheck_five_ledgers_equal'] is True
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
    assert sum(row['runs']['full']['center_pass'] for row in rows) == 1
    assert sum(row['runs']['s011_common']['dual_pass'] for row in rows) == 0
    assert sum(row['both_center_pass'] for row in rows) == result['qualified_centers'] == 0
    audits = {'account_audit.json': read(HERE / 'others/account_audit.json')}
    for name in ('training_audit.json', 'runtime_checks.json'):
        reference = EvidenceRef.from_dict(protocol['dependencies']['others/' + name])
        audits[name] = read(reference.resolve(ROOT))
    audits['permission_runtime_checks.json'] = read(HERE / 'others/runtime_checks.json')
    assert audits['permission_runtime_checks.json']['source_sha256'] == sha256((HERE / 'src/strategy_runtime/strategies/price_information.py').read_bytes()).hexdigest()
    assert all(audit['status'] == 'PASS' for audit in audits.values())
    audit = audits['account_audit.json']
    assert len(audit['accounts']) == 24 and audit['formal_ledger_exports_checked'] == 120
    assert audit['feature_prediction_intention_rows'] == 10188 and audit['input_checks_count'] == 72
    assert audit['canonical_window_equivalence'] == 'PASS'
    accounts = {(item['candidate'], item['window']): item for item in audit['accounts']}
    assert len(accounts) == 24
    for row in rows:
        for window, run in row['runs'].items():
            item = accounts[row['candidate_id'], window]
            assert item['parameters'] == row['parameters'] and item['ledger_reconciliation'] == 'PASS'
            for key in ('net_return', 'cagr', 'dd', 'closed', 'frequency_median', 'frequency_good', 'frequency_windows'):
                assert abs(item[key] - run[key]) < 1e-10, (row['candidate_id'], window, key)
    differences = read(HERE / 'others/input_difference_observed.json')
    assert len(differences['differences']) == 24
    return result, audits, differences


def report():
    assert not (HERE / 'others/published_refs.json').exists(), 'Published experiment report is immutable'
    result, audits, differences = inputs()
    rows = result['rows']; benchmark = rows[0]['runs']['full']
    protocol = read(HERE / 'protocols/accounts.json')
    permission = EX.experiment_id == 'EX045_20261023'
    title = '许可失效退出账户对照' if permission else '固定持有九日边界核验'
    count = len(rows); full_pass = sum(row['runs']['full']['center_pass'] for row in rows)
    lines = [f'# S015 {title}', '', 'Status: COMPLETED', '',
             f'{count}个事前固定配置完成{2*count}个正式账户窗口场景，另有{result["technical_precheck_extra_scenarios"]}个技术重复场景。434日原中心门通过{full_pass}/{count}，415日严格双目标和联合中心均0/{count}。新增合格候选为0，本实验不构成本轮阶段三最终交付；没有登记或交接候选，没有执行阶段四32点扰动和费用压力。', '',
             '## 研究问题与预设范围', '', protocol['question'], '', protocol['selection_history'], '']
    if permission:
        lines += ['A/B两套模型×path/risk/and三种许可×最大意图年龄3、7，共12配置，唯一新增类别为permission退出。复用EX042三日和EX043七日的同家族同许可固定持有对照，共12个旧配置，不重复计算或计数。', '',
                  '收盘时若当前许可失效或意图年龄达到上限，发出退出目标，下一交易日按原市场卖出规则执行；当日退出决定不重新入场。许可由当时已知预测计算，不能阻止当天已经发生的损失。path只检查收益许可，risk只检查风险许可，and任一许可失效即退出。模型、学习时钟、许可阈值、仓位比例和执行费用均未调整。']
    else:
        lines += ['仅扩展A家族path/risk/and至hold=9，使用100%可用现金比例。EX043的7日A/risk和A/and原中心通过，但415日不通过；A/path由5至7日也改善。原协议未因B的7日表现继续扩展B。本轮不新增模型、训练、组件、许可阈值、仓位或退出规则；9日是临时边界，未测试长度不得直接判失败。']
    lines += ['', 'A模型只用价格路径或波动转换表达；B模型在对应表达前加入过去1/5日收益、20日波动/振幅及当日量价压力旧控制。path为收益预测非负许可，risk为风险预测低于当时训练阈值许可，and为两者同时满足。统一运行时计算13个特征，A模型不使用旧控制列。', '',
              '复用EX042的20个历史生效日期与80套模型拟合，本轮新增拟合0。30个成熟标签起训、每20日更新、Ridge正则10；标签可得日严格早于生效日期，标准化与风险中位阈值来自当时训练集。模型参数与时间线不可变，属于历史研究重放，未实现部署后自动训练。Optuna仅排队固定配置，没有在本实验内继续寻优。', '',
              '## 全部正式账户结果', '',
              '434日为2025-01-02至2026-10-21，415日为2025-02-06至2026-10-21，各自独立10万元、空仓初始化。净收益已扣实际费用，回撤包含初始资金；年化、闭合周期、频率与费用列取434日。', '',
              '| 原型 | 模型/许可 | hold | 两窗净收益 | 两窗回撤 | 434日年化 | 闭合周期 | 60日频率中位 | ≥3笔窗口 | 费用（元） | 434日未通过项 |',
              '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in rows:
        p = row['parameters']; f = row['runs']['full']
        failed = '、'.join(CHECK_NAMES[key] for key, passed in f['checks'].items() if not passed) or '无（中心通过）'
        lines.append(f"| {row['candidate_id']} | {p['family']}/{p['mode']} | {p['hold']} | {100*f['net_return']:.3f}% | {100*f['dd']:.3f}% | {100*f['cagr']:.3f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']}/{f['frequency_windows']} | {f['fees']:.2f} | {failed} |")
    lines += ['', '首次模型生效日2025-02-27，为开发池位置34。此前34个开发交易日持有现金，415日窗口也在首次生效前开始；同一模型时间线和相同初始资金使每配置两窗后续交易路径相同，净收益与回撤完全相同。年化分母、净值长度与频率窗口仍不同；未继承434日账户切片持仓，也不能当两份独立验证样本。', '',
              f"434日可执行LimitBuyHold基准年化{100*benchmark['benchmark_cagr']:.6f}%、回撤{100*benchmark['benchmark_dd']:.6f}%。原中心门要求年化至少{150*benchmark['benchmark_cagr']:.6f}%，回撤同时不超过{80*benchmark['benchmark_dd']:.6f}%与25%；60日闭合交易中位至少6笔，375个完整窗口至少338个有3笔。", '',
              f'415日只检验固定S011严格双目标：净收益>{100*RETURN_GATE:.9f}%且最大回撤幅度<{100*DD_GATE:.9f}%，按未取整原值比较，相等不通过。本实验每个配置的415日收益和回撤门均未通过。JSON所保存的415日普通基准检查是诊断，不能用作新增门槛。原中心通过不等于双窗联合中心，更不等于含扰动和费用压力的完整资格。', '',
              '## 对照解释与边界', '']
    if permission:
        controls = {}
        for payload in protocol['controls_results']:
            for row in read(EvidenceRef.from_dict(payload).resolve(ROOT))['rows']:
                p = row['parameters']
                if p['hold'] in (3, 7):
                    controls[p['family'], p['mode'], p['hold']] = row['runs']['full']
        assert len(controls) == 12
        lines += ['| 原型 | 固定持有净收益 | 许可退出净收益 | 固定持有回撤 | 许可退出回撤 |', '| --- | ---: | ---: | ---: | ---: |']
        for row in rows:
            p = row['parameters']; old = controls[p['family'], p['mode'], p['hold']]; new = row['runs']['full']
            lines.append(f"| {row['candidate_id']} | {100*old['net_return']:.3f}% | {100*new['net_return']:.3f}% | {100*old['dd']:.3f}% | {100*new['dd']:.3f}% |")
        lines += ['', 'B/path/7是本实验最高净收益配置：59.230%、回撤18.467%，原中心通过；相对固定7日30.258%/30.359%两项改善，但仍达不到415日91.580%/7.249%严格门。A/risk/7则由56.534%/16.538%变为5.632%/24.750%，收益大幅减少且回撤变差。许可失效退出不普遍改善策略，不能只展示B/path成功方向而删去A/risk反例。', '',
                  '最大年龄7仍为本次边界，不能断言更多整数长度无效或充分搜索。后续若依事前边界原则补齐持有域，应独立冻结并保留本轮全量结果；不得把对照改善解释为新样本验证。']
    else:
        lines += ['A/path/9净收益36.538%、回撤30.175%，相对7日的34.332%/33.697%略有改善，却仍同时未过原收益和回撤门。A/risk/9净收益12.519%、回撤34.111%；A/and/9净收益11.363%、回撤30.906%，均明显弱于各自7日对照。三者回撤均超过30%，risk/and的频率中位分别5/4，也未达到6。', '',
                  '结果不支持把A/risk或A/and从7日继续延长就能保留原中心优势。A/path仍存在有限方向改善，不能凭本次三配置全失败宣称整数持有域已穷尽；剩余长度与频率可行性需要独立协议或明确上界诊断。']
        bound = HERE / 'others/frequency_bound.json'
        if bound.exists():
            lines += ['', '独立频率上界诊断另见[频率可行性证据](others/frequency_bound.json)。该证据只约束其明确声明的交易时钟、持有和窗口定义，不替代未测配置的收益/回撤账户结论。']
    lines += ['', '阶段二每次重新投入10万元的独立事件可重叠，连续账户则共享资金并排斥重叠机会，受成交路径、复利和费用影响；阶段二四折与位置34起的学习日程也不同。事件均值不能直接当作账户预期，本轮只确认已测试构造没有达到双窗目标。', '',
              '## 执行语义与独立审计', '',
              '采用available_cash_fraction/entry_cycle：周期入场时按可用现金比例锁定目标数量，正意图期间允许继续尝试未完成买入，不按每日净资产重配。hold约束意图年龄，未成交日也消耗时钟；实际持仓间隔逐周期核对。补买不另计闭合周期，末端未平仓按收盘估值、不强制卖出。1%限价买入、原tick/lot/涨跌幅保护、市场卖出、每侧0.1%费用、HFQ_RESEARCH与DAILY_RANGE_V3保持不变。', '']
    audit = audits['account_audit.json']
    lines += [f"账户审计PASS，独立核对{len(audit['accounts'])}个正式场景、{audit['formal_ledger_exports_checked']}份五类账本、{audit['input_checks_count']}份输入以及{audit['feature_prediction_intention_rows']}行实际特征/预测/许可/意图；资金账本、周期锁定数量、实际持有间隔、闭合交易频率和两窗一致性均通过。审计没有重新prepare或evaluate。", '']
    if permission:
        lines += ['本轮新运行时的fixed模式与旧源12配置的全部5208行开发期输出一致；permission模式独立重建状态机，84个意图历史前缀一致。实际账户每个上限前退出均核对当前许可失效，实际持有天数与意图年龄、延迟入场及次日卖出时间逐周期核对。信号周期诊断不是实际闭合交易数。', '',
                  '主运行器对首配置进行串行与并行重复，两窗口account_daily、decisions、orders、fills、trades五类账本及结果hash一致。另2个技术重复场景不计入24正式场景或新配置；串行账本未另行持久化，账户独立审计不另行重跑该技术比较。']
    else:
        lines += ['本轮无新增技术重复账户，precheck_five_ledgers_equal=false表示没有重做，而非比较失败。复用EX042执行路径预检；该主运行器记录两窗五账本串并行一致，串行账本未独立持久化，本轮审计没有另行复现。']
    lines += ['', 'EX042短ID绑定的首次prepare曾在账户运行前被拒绝，冻结技术补充改为完整身份；本轮直接复用修正，不把旧失败prepare计为新账户。主计算最多4进程、每进程原生线程1，固定任务全部完成。毛收益是实际成交现金流加末端估值的扣费前归因，不是零费重跑；入场/后续毛收益不是可避免损失的因果估计。周期、损益和失败订单细节全部保留。', '',
              '## 输入差异披露', '']
    sample = differences['differences'][0]; volume = sample['unused_field_differences']['Volume']
    lines += [f"实际盘中输入相对旧认证快照的{sample['rows']}行中，Volume有{volume['rows']}行不同，最大绝对差{volume['max_absolute']:.0f}，最大相对差{volume['max_relative']:.9g}。各场景记录同一底层差异，不能重复算作独立数据变化。盘中实际使用的OHLC、Amount、AvailableDate及日线使用字段均精确一致，不能声称全字段或数据身份完全一致。", '',
              f"盘中Volume未进入13个特征，执行未启用成交量容量约束；全部{audit['feature_prediction_intention_rows']}行实际特征/预测/许可/意图一致。该等价证据仅覆盖本轮使用信息，不扩大到其他用途；新旧身份和差异原件均保留。", '',
              '## 发布范围和下一步', '',
              '账户审计、历史训练审计及相应运行契约核验均PASS；技术正确不代表预测有效或目标达标。本脚本只发布本实验材料和报告，不组装CANDIDATES、不改研究族、不发布ASSESSMENT，不进入阶段四或PTE。下一步由阶段三在独立后继协议完成有明确边界的剩余构造核验后统一交付；如仍无双窗合格中心，采用空交接集合如实收尾。', '',
              '证据：[冻结协议](protocols/accounts.json)、[全部结果](others/results.json)、[账户审计](others/account_audit.json)、[周期明细](others/audit_cycle_details.csv)、[输入差异](others/input_difference_observed.json)、[冻结引用](others/protocol_refs.json)。模型、历史对照和训练核验通过协议EvidenceRef认证。']
    (HERE / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(EX.experiment_id[:5] + '_REPORT_READY', flush=True)


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
    print('EX045_PUBLISHED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('report', 'publish'))
    {'report': report, 'publish': publish}[parser.parse_args().mode]()
