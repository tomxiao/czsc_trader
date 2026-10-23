"""Report and publish the fixed prospective account experiment; no candidate handoff."""
import argparse
import csv
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
    authenticate(protocol['runtime_source_validation'], HERE.parent / 'EX045_20261023')
    for reference in evidence_refs(protocol):
        assert reference.experiment.strategy_id == 'S015'
        reference.resolve(ROOT)
    rows = result['rows']
    assert len(rows) == len({row['candidate_id'] for row in rows}) == 47
    assert [row['parameters'] for row in rows] == protocol['configurations']
    assert result['new_configurations'] == 47 and result['account_scenarios'] == 94
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
    assert sum(row['both_center_pass'] for row in rows) == result['qualified_centers']
    audits = {'account_audit.json': read(HERE / 'others/account_audit.json'),
              'summary_audit.json': read(HERE / 'others/summary_audit.json')}
    for name in ('training_audit.json', 'runtime_checks.json'):
        reference = EvidenceRef.from_dict(protocol['dependencies']['others/' + name])
        audits[name] = read(reference.resolve(ROOT))
    audits['permission_runtime_checks.json'] = read(HERE / 'others/runtime_checks.json')
    assert audits['permission_runtime_checks.json']['permission_runtime_sha256'] == EvidenceRef.from_dict(protocol['source_ref']).sha256
    assert audits['permission_runtime_checks.json']['maximum_permission_runs'] == protocol['maximum_permission_runs']
    assert audits['permission_runtime_checks.json']['finite_domain_representatives'] == 155
    assert sum(protocol['maximum_permission_runs'].values()) == 101
    assert all(audit['status'] == 'PASS' for audit in audits.values())
    for name, evidence in audits.items():
        directory = PREV if name in ('training_audit.json', 'runtime_checks.json') else HERE
        for relative, digest in evidence.get('sha256', {}).items():
            assert sha256((directory / relative).read_bytes()).hexdigest() == digest, relative
    audit = audits['account_audit.json']
    assert len(audit['accounts']) == 94 and audit['formal_ledger_exports_checked'] == 470
    assert audit['feature_prediction_intention_rows'] == 39903 and audit['input_checks_count'] == 282
    assert audit['canonical_window_equivalence'] == 'PASS'
    accounts = {(item['candidate'], item['window']): item for item in audit['accounts']}
    assert len(accounts) == 94
    for row in rows:
        for window, run in row['runs'].items():
            item = accounts[row['candidate_id'], window]
            assert item['parameters'] == row['parameters'] and item['ledger_reconciliation'] == 'PASS'
            for key in ('net_return', 'cagr', 'dd', 'closed', 'frequency_median', 'frequency_good', 'frequency_windows'):
                assert abs(item[key] - run[key]) < 1e-10, (row['candidate_id'], window, key)
    differences = read(HERE / 'others/input_difference_observed.json')
    assert len(differences['differences']) == 94
    summary = read(HERE / 'others/search_summary.json')
    assert summary['status'] == 'COMPLETED_DESCRIPTIVE_ARITHMETIC'
    assert (summary['total_configurations'], summary['standard_accounts'], summary['technical_repeat_accounts']) == (159, 318, 4)
    for relative, digest in summary['source_hashes'].items():
        assert sha256((HERE.parent / relative).read_bytes()).hexdigest() == digest, relative
    combined = []
    for payload in protocol['controls_results']:
        reference = EvidenceRef.from_dict(payload)
        assert reference.resolve(ROOT).read_bytes() == (HERE.parent / reference.experiment.experiment_id / 'others/results.json').read_bytes()
        combined.extend(read(reference.resolve(ROOT))['rows'])
    assert len(combined) == 112
    combined += rows
    key = lambda r: (r['parameters']['family'], r['parameters']['mode'], r['parameters'].get('exit_rule', 'fixed'), r['parameters']['hold'])
    actual = set(map(key, combined))
    expected = {(f, m, 'fixed', h) for f in ('A', 'B') for m in ('path', 'risk', 'and') for h in range(1, 10)}
    expected |= {(fm.split('/')[0], fm.split('/')[1], 'permission', h) for fm, maximum in protocol['maximum_permission_runs'].items() for h in range(1, maximum + 1)}
    expected |= {('A', 'and', 'permission', 9), ('B', 'path', 'permission', 30), ('B', 'and', 'permission', 15), ('B', 'and', 'permission', 30)}
    assert len(combined) == len(actual) == 159 and actual == expected
    assert summary['full_center_pass'] == sum(r['runs']['full']['center_pass'] for r in combined)
    assert summary['joint_pass'] == sum(r['both_center_pass'] for r in combined)
    assert summary['common_return_pass'] == sum(r['runs']['s011_common']['return_superior'] for r in combined)
    assert summary['common_dd_pass'] == sum(r['runs']['s011_common']['dd_superior'] for r in combined)
    assert summary['best_return']['net_return'] == max(r['runs']['full']['net_return'] for r in combined)
    assert summary['lowest_dd']['dd'] == min(r['runs']['full']['dd'] for r in combined)
    with (HERE / 'others/all_centers.csv').open(encoding='utf-8', newline='') as stream:
        centers = list(csv.DictReader(stream))
    assert len(centers) == 159
    by_id = {r['candidate_id']: r for r in combined}
    assert {r['candidate'] for r in centers} == set(by_id)
    for row in centers:
        original = by_id[row['candidate']]
        for field in ('net_return', 'dd', 'cagr'):
            assert abs(float(row[field]) - original['runs']['full'][field]) < 1e-12
    return result, audits, differences, summary


def report():
    assert not (HERE / 'others/published_refs.json').exists(), 'Published experiment report is immutable'
    result, audits, differences, summary = inputs()
    rows = result['rows']; benchmark = rows[0]['runs']['full']; protocol = read(HERE / 'protocols/accounts.json')
    full_count = sum(r['runs']['full']['center_pass'] for r in rows)
    common_count = sum(r['runs']['s011_common']['dual_pass'] for r in rows)
    lines = ['# S015 许可退出有限持有域补齐', '', 'Status: COMPLETED', '',
             f"本实验新增47配置、94个正式账户窗口，新增技术重复0。434日原中心门通过{full_count}/47，415日严格双目标通过{common_count}/47，两窗联合中心通过{result['qualified_centers']}/47。累计EX042—047共159个参数身份、318个正式窗口账户，另有4个历史技术重复；原中心通过{summary['full_center_pass']}/159，两窗联合中心通过{summary['joint_pass']}/159。旧112配置不重复计算，历史报告不改写。", '',
             '本报告发布实验结果和边界证据，不登记或交接候选；最终阶段三由CANDIDATES/5统一交付。报告及技术审计PASS不等于策略经济达标；本轮未执行阶段四32点扰动、费用压力、冻结或PTE。', '',
             '## 问题、选择历史与范围', '', protocol['question'], '', protocol['selection_history'], '',
             '新增A/path许可上限10..16共7个、A/risk10..18共9个、B/path10..22排除已测15共12个、B/risk10..24共15个、B/and10..13共4个；A/and无需新增。47配置在执行前固定，Optuna仅排队记录，未根据本轮成绩改变模型、阈值、仓位或配置集合。', '',
             '复用EX045的冻结运行时与EX042模型：A只用价格路径或波动转换表达；B加入过去1/5日收益、20日波动/振幅和当日量价压力旧控制。path为预测净收益非负许可，risk为预测风险不高于当时训练阈值许可，and同时要求两者。全部13特征、20个历史模型生效日期及80套拟合均复用，新增拟合0。', '',
             '模型至少30个成熟标签后开始训练，每20日更新，Ridge正则10；标签可得日严格早于生效日期，标准化和风险阈值来自当时训练集。运行只选择已生效冻结参数。这是截至2026-10-21的历史研究重放，不是部署后自动更新系统；时序正确不消除已见开发池的研究选择历史。', '',
             '## 全部47个新增账户', '',
             '434日为2025-01-02至2026-10-21，415日为2025-02-06至2026-10-21，各自独立10万元、空仓初始化。净收益已扣实际费用，回撤包括初始资金；年化、费用和频率列为434日。所有新增配置均为permission退出。', '',
             '| 原型 | 模型/许可 | 最大年龄 | 两窗净收益 | 两窗回撤 | 434日年化 | 闭合周期 | 频率中位 | ≥3笔窗口 | 费用（元） | 原中心未通过项 |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in rows:
        p = row['parameters']; f = row['runs']['full']
        failed = '、'.join(CHECK_NAMES[k] for k, passed in f['checks'].items() if not passed) or '无（原中心通过）'
        lines.append(f"| {row['candidate_id']} | {p['family']}/{p['mode']} | {p['hold']} | {100*f['net_return']:.3f}% | {100*f['dd']:.3f}% | {100*f['cagr']:.3f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']}/{f['frequency_windows']} | {f['fees']:.2f} | {failed} |")
    lines += ['', '首次模型在开发池位置34、2025-02-27生效，此前34个交易日持有现金；415日窗口也在首次模型前开始。因此每配置在两窗后续交易路径相同，净收益与回撤相同；年化分母、净值长度和频率窗口不同。两窗重新初始化、没有切片继承仓位，不能作为两份独立预测样本。', '',
              f"434日基准年化{100*benchmark['benchmark_cagr']:.6f}%、回撤{100*benchmark['benchmark_dd']:.6f}%；原中心要求年化至少{150*benchmark['benchmark_cagr']:.6f}%，回撤同时不超过{80*benchmark['benchmark_dd']:.6f}%与25%，60日闭合交易中位至少6笔、375窗至少338窗有3笔。", '',
              f'415日只检验净收益>{100*RETURN_GATE:.9f}%且回撤<{100*DD_GATE:.9f}%，按未取整原值严格比较，相等不通过。结果JSON中的415日普通基准检查仅作诊断，不新增验收门。收益不能补偿回撤，中心通过不等于完整默认资格。', '',
              '## 有限边界的证明与适用范围', '',
              '固定退出的六组合均已覆盖整数1..9，共54个配置。EX044代数证明在当前无提前退出的单持仓二元周期中H≥10无法满足原频率门：H=10至多175/375窗达到6笔，少于中位达到6所需188窗；H≥11没有窗口能容纳6次闭合。该结论仅适用于声明的固定周期，不用于许可退出。', '',
              '| 家族/许可 | 样本内最长连续许可长度M | 本次新增范围 | 已覆盖许可代表域 |',
              '| --- | ---: | --- | --- |']
    ranges = {'A/path': '10..16', 'A/risk': '10..18', 'A/and': '无', 'B/path': '10..22，除已测15', 'B/risk': '10..24', 'B/and': '10..13'}
    for fm, maximum in protocol['maximum_permission_runs'].items():
        lines.append(f'| {fm} | {maximum} | {ranges[fm]} | 1..{maximum} |')
    lines += ['', '许可与hold无关，只由同一输入、模型时间线和阈值决定。规范起点为空仓意图，每个false日把年龄归零且不新开周期；连续true段长度至多M，第M个true日开始时年龄至多M−1。因此任何hold≥M都不会在true段内因年龄提前退出；下一false日共同退出，样本末端截断时也保持相同状态。逐段归纳，所有hold≥M在本固定序列上的全部输出与hold=M相同。', '',
              '边界核验使用认证EX036特征、EX042模型与EX045冻结源，比较每组M、M+1、434的全部435行规范输出，并以独立标量状态机重建年龄/目标；再验证4个已测超界身份：A/and/9对应M=8、B/path/30对应M=22、B/and/15和30对应M=13。', '',
              '54个fixed表达加101个permission代表表达为155；再加上述4个已测冗余参数身份，累计159。155也不保证155条不同意图路径，更不是独立信号数。最长段是全开发池事后计算的研究搜索边界，不是当时可预知的未来持续时间；不能推广到未来行情、新模型、不同许可、起点或执行合同。信号等价本身不构成新账户收益证据。', '',
              '## 累计159配置的描述性结果', '',
              f"累计415日收益单门通过{summary['common_return_pass']}/159、回撤单门通过{summary['common_dd_pass']}/159，联合中心通过{summary['joint_pass']}/159。全量结果见[159配置表](others/all_centers.csv)。各组最高收益与最低回撤可能来自不同配置，不能拼接为同一策略。", '',
              '| 家族/许可 | 退出 | 参数身份数 | 最高收益hold | 净收益 | 对应回撤 | 最低回撤hold | 回撤 | 对应净收益 |',
              '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for item in summary['family_summary']:
        best, low = item['best_return'], item['lowest_dd']
        lines.append(f"| {item['family']}/{item['mode']} | {item['exit_rule']} | {item['count']} | {best['parameters']['hold']} | {100*best['net_return']:.3f}% | {100*best['dd']:.3f}% | {low['parameters']['hold']} | {100*low['dd']:.3f}% | {100*low['net_return']:.3f}% |")
    best, low = summary['best_return'], summary['lowest_dd']
    lines += ['', f"最高净收益为{best['experiment']}/{best['candidate']}：{100*best['net_return']:.3f}%，回撤{100*best['dd']:.3f}%，频率中位{best['frequency_median']:.0f}，原中心{'通过' if best['full_pass'] else '未通过'}。最低回撤为{low['experiment']}/{low['candidate']}：{100*low['dd']:.3f}%，对应收益{100*low['net_return']:.3f}%。这些极值来自已反复观察的开发池，不能当作独立验证。", '',
              '完整原中心通过清单与收益/回撤前沿在search_summary.json中；前沿忽略频率，仅为描述。年度及步长21日的252日切片继承原资金和持仓，没有重新注资；局部峰值回撤与继承历史峰值回撤分别记录，部分日历年度不年化，不新增经济硬门。', '',
              '阶段二独立事件每次重置10万元且可重叠；实际账户共享资金、排斥重叠机会，受成交路径、复利与费用约束，历史训练日程也与阶段二四折不同。组件的有限信息用途不能直接推为账户预期。许可失效退出并非普遍改善：既有A/risk/7反例保留，不能只挑改善的B/path叙事。', '',
              '## 账户审计与输入差异', '']
    audit = audits['account_audit.json']
    lines += [f"独立账户审计PASS：{len(audit['accounts'])}个正式场景、{audit['formal_ledger_exports_checked']}份五类账本、{audit['input_checks_count']}份输入及{audit['feature_prediction_intention_rows']}行实际特征/预测/许可/意图；实际模型/参数身份、资金账本、执行手续费、周期和频率均核对。运行边界与复用训练核验均PASS。", '',
              '收盘许可失效或年龄届满产生退出意图，下一交易日按市场卖出合同执行；不能挽回当天已经发生的亏损，退出决定当日不重新入场。available_cash_fraction/entry_cycle入场时锁定周期数量，正意图内可继续尝试未完成买入，补买不另计闭合周期。实际持有天数与意图年龄、延迟入场和次日执行逐周期核对；末端未平仓估值但不强制卖出。', '',
              '累计汇总的额外独立审计summary_audit.json为PASS，核对159身份域、318正式账户与4技术重复、极值及时间切片，并核验许可有限界证明；它不新增账户或独立样本。', '',
              '1%买入限价、原tick/lot与涨跌幅保护、每侧0.1%费用、HFQ_RESEARCH、DAILY_RANGE_V3及100%可用现金比例不变。本轮新增技术账户0，复用EX042/45的4个串并行重复场景；原运行器记录两窗五账本/hash一致，串行账本未另持久化，独立审计不重新执行该比较。precheck_five_ledgers_equal=false表示本轮未重做，不是比较失败。', '',
              'EX042短IDprepare拒绝发生在账户运行前，本轮使用已认证完整身份修正，不计为新账户。毛收益是实际成交现金流加末端估值的扣费前归因，不是零手续费重跑；入场/后续拆分不能当可避免损失的因果证明。', '']
    sample = differences['differences'][0]; volume = sample['unused_field_differences']['Volume']
    lines += [f"实际盘中{sample['rows']}行中Volume相对旧认证快照有{volume['rows']}行尾差，最大绝对差{volume['max_absolute']:.0f}、最大相对差{volume['max_relative']:.9g}；94场景披露同一底层差异，不重复算作独立数据变化。实际使用的盘中OHLC、Amount、AvailableDate及日线字段精确一致，不能声称全字段或数据身份相同。盘中Volume不进入13特征，未启用成交量容量限制；全部39903行实际预测链已核验。差异原件和身份保留，等价范围不扩大至其他用途。", '',
              '## 判断与下一步', '']
    if summary['joint_pass']:
        lines += ['累计已有联合中心通过者，下一步应由阶段三统一交付，按原要求评审后续资格检验。不得跳过扰动、费用压力或必要授权，不因技术报告发布而宣称完整达标。']
    else:
        lines += ['累计无联合中心通过者。建议结束当前固定模型、许可、全仓和执行合同下的期限/退出调参，并以空交接集合如实完成阶段三交付。理由是声明的有限构造域及等价边界已经核验，并非额度耗尽；继续增加已等价的hold不能增加有效实验。总体产出达标策略的目标仍未达成，不应进入阶段四。下一研究建议回到可交易收益机制诊断，先说明新的信息或模型为何有望改善，再决定是否启动另一组件路线；现结果不证明所有价格信息无效。']
    lines += ['', '本脚本只出版EX047材料与报告，不组装CANDIDATES、不更新研究族状态、不发布ASSESSMENT。最终CANDIDATES/5由主会话统一执行，完整保留历史失败、边界证据和选择历史。', '',
              '证据：[冻结协议](protocols/accounts.json)、[47配置结果](others/results.json)、[累计汇总](others/search_summary.json)、[159配置表](others/all_centers.csv)、[运行边界](others/runtime_checks.json)、[账户审计](others/account_audit.json)、[汇总独立审计](others/summary_audit.json)、[输入差异](others/input_difference_observed.json)。旧对照、源、模型和固定频率证明以协议EvidenceRef认证。']
    (HERE / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print('EX047_REPORT_READY', flush=True)


def publish():
    assert not (HERE / 'others/published_refs.json').exists(), 'Already published; never overwrite'
    result, _, _, _ = inputs()
    report()
    files = sorted(path for folder in ('src', 'protocols', 'others') for path in (HERE / folder).rglob('*')
                   if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.json', '.csv', '.md')
                   and path.name not in ('published_refs.json', 'deliver.py', 'stage3_report.md', 'delivery_validation.json'))
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
    print('EX047_PUBLISHED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('report', 'publish'))
    {'report': report, 'publish': publish}[parser.parse_args().mode]()
