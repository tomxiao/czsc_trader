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
    assert len(rows) == len({row['candidate_id'] for row in rows}) == 67
    assert [row['parameters'] for row in rows] == protocol['configurations']
    assert result['new_configurations'] == 67 and result['account_scenarios'] == 134
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
    audits = {'account_audit.json': read(HERE / 'others/account_audit.json')}
    for name in ('training_audit.json', 'runtime_checks.json'):
        reference = EvidenceRef.from_dict(protocol['dependencies']['others/' + name])
        audits[name] = read(reference.resolve(ROOT))
    audits['permission_runtime_checks.json'] = read(HERE / 'others/runtime_checks.json')
    assert audits['permission_runtime_checks.json']['permission_runtime_sha256'] == EvidenceRef.from_dict(protocol['source_ref']).sha256
    assert audits['permission_runtime_checks.json']['fixed_equivalent_configs'] == 54
    assert all(audit['status'] == 'PASS' for audit in audits.values())
    audit = audits['account_audit.json']
    assert len(audit['accounts']) == 134 and audit['formal_ledger_exports_checked'] == 670
    assert audit['feature_prediction_intention_rows'] == 56883 and audit['input_checks_count'] == 402
    assert audit['canonical_window_equivalence'] == 'PASS'
    accounts = {(item['candidate'], item['window']): item for item in audit['accounts']}
    assert len(accounts) == 134
    for row in rows:
        for window, run in row['runs'].items():
            item = accounts[row['candidate_id'], window]
            assert item['parameters'] == row['parameters'] and item['ledger_reconciliation'] == 'PASS'
            for key in ('net_return', 'cagr', 'dd', 'closed', 'frequency_median', 'frequency_good', 'frequency_windows'):
                assert abs(item[key] - run[key]) < 1e-10, (row['candidate_id'], window, key)
    differences = read(HERE / 'others/input_difference_observed.json')
    assert len(differences['differences']) == 134
    summary = read(HERE / 'others/search_summary.json')
    assert summary['status'] == 'COMPLETED_DESCRIPTIVE_ARITHMETIC'
    assert (summary['total_configurations'], summary['standard_accounts'], summary['technical_repeat_accounts']) == (112, 224, 4)
    for relative, digest in summary['source_hashes'].items():
        assert sha256((HERE.parent / relative).read_bytes()).hexdigest() == digest, relative
    combined = []
    for payload in protocol['controls_results']:
        reference = EvidenceRef.from_dict(payload)
        combined.extend(read(reference.resolve(ROOT))['rows'])
    assert len(combined) == 45
    combined += rows
    key = lambda r: (r['parameters']['family'], r['parameters']['mode'], r['parameters'].get('exit_rule', 'fixed'), r['parameters']['hold'])
    actual = set(map(key, combined))
    expected = {(f, m, e, h) for f in ('A', 'B') for m in ('path', 'risk', 'and') for e in ('fixed', 'permission') for h in range(1, 10)}
    expected |= {('B', m, 'permission', h) for m in ('path', 'and') for h in (15, 30)}
    assert len(combined) == len(actual) == 112 and actual == expected
    assert summary['full_center_pass'] == sum(r['runs']['full']['center_pass'] for r in combined)
    assert summary['joint_pass'] == sum(r['both_center_pass'] for r in combined)
    assert summary['common_return_pass'] == sum(r['runs']['s011_common']['return_superior'] for r in combined)
    assert summary['common_dd_pass'] == sum(r['runs']['s011_common']['dd_superior'] for r in combined)
    assert summary['best_return']['net_return'] == max(r['runs']['full']['net_return'] for r in combined)
    assert summary['lowest_dd']['dd'] == min(r['runs']['full']['dd'] for r in combined)
    with (HERE / 'others/all_centers.csv').open(encoding='utf-8', newline='') as stream:
        centers = list(csv.DictReader(stream))
    assert len(centers) == 112
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
    lines = ['# S015 有限整数持有域补全及许可退出长边界', '', 'Status: COMPLETED', '',
             f"本实验新增67配置、134个正式账户窗口，技术重复0。434日原中心门通过{full_count}/67，415日严格双目标通过{common_count}/67，两窗联合中心通过{result['qualified_centers']}/67。累计EX042—046共112配置、224个正式账户窗口，另有4个历史技术重复；原中心通过{summary['full_center_pass']}/112，两窗联合中心通过{summary['joint_pass']}/112。当前实验和累计研究范围分别计数，旧45配置不重复计算。", '',
              '本报告为累计112配置的中期记录。EX047已另立后继实验，将用许可连续有效段的有限界补齐未测中间整数；其结果不并入本实验计数。本报告不登记或交接候选，不代表完整资格；32点扰动与费用压力尚未执行。', '',
             '## 事前研究范围', '', protocol['question'], '', protocol['selection_history'], '',
             '新增固定退出21配置：六种家族/许可组合的hold=4、6、8，以及B三种许可的hold=9；新增许可失效退出42配置：六组合的hold=1、2、4、5、6、8、9；另增B/path、B/and许可退出的上限15、30共4配置。连同旧45配置，恰覆盖六组合×两退出规则×整数1..9共108配置，加4个长边界。参数不同可能产生相同意图路径，112不是112个独立信号或独立验证样本。', '',
             '全部复用EX045冻结运行时，fixed模式已对A/B×path/risk/and×hold1..9全部54配置的435行规范输出核对，与EX042旧源完全一致。permission模式在意图年龄届满或当日许可失效时发退出意图，次日市场卖出，当日不重入。固定规则在意图年龄届满前不因许可失效退出。', '',
             'A仅使用价格路径或波动转换表达；B加入过去1/5日收益、20日波动/振幅和当日量价压力旧控制。path为收益预测非负许可，risk为风险预测不超过训练阈值许可，and为两者同时满足。13个特征、EX042的20个生效日期/80套模型拟合、模型阈值和100%可用现金比例均不改变，本轮新增拟合0。标签可得日严格早于模型生效日；标准化与风险中位阈值来自当时训练集。历史研究重放不等于部署后的自动训练更新。', '',
             '## 新增67配置的全部结果', '',
             '434日为2025-01-02至2026-10-21，415日为2025-02-06至2026-10-21，各自独立10万元空仓开始。净收益已扣费，回撤包含初始资金；年化、费用和频率列为434日。全部失败结果保留。', '',
             '| 原型 | 模型/许可 | 退出 | hold | 两窗净收益 | 两窗回撤 | 434日年化 | 闭合周期 | 频率中位 | ≥3笔窗口 | 费用（元） | 原中心未通过项 |',
             '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in rows:
        p = row['parameters']; f = row['runs']['full']
        failed = '、'.join(CHECK_NAMES[k] for k, passed in f['checks'].items() if not passed) or '无（原中心通过）'
        lines.append(f"| {row['candidate_id']} | {p['family']}/{p['mode']} | {p['exit_rule']} | {p['hold']} | {100*f['net_return']:.3f}% | {100*f['dd']:.3f}% | {100*f['cagr']:.3f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']}/{f['frequency_windows']} | {f['fees']:.2f} | {failed} |")
    lines += ['', '开发池最初34个交易日没有已生效模型，首个生效日2025-02-27；共同415日窗口也在首次生效前开始。相同初始资金与规范学习时间线使两窗后续交易路径一致，每配置两窗净收益/回撤相同；年化分母、频率窗口及净值长度不同。两窗是独立初始化，未切片继承持仓，也不构成两份独立预测检验。', '',
              f"434日基准年化{100*benchmark['benchmark_cagr']:.6f}%、回撤{100*benchmark['benchmark_dd']:.6f}%；中心要求年化至少{150*benchmark['benchmark_cagr']:.6f}%，回撤同时不超过{80*benchmark['benchmark_dd']:.6f}%与25%，60日闭合交易中位至少6笔、375窗至少338窗有3笔。", '',
              f'415日要求净收益>{100*RETURN_GATE:.9f}%且回撤<{100*DD_GATE:.9f}%，按未取整原值严格比较，相等不通过。JSON中的415日普通基准检查仅作诊断，未添加新经济门槛。中心通过不代替扰动或费用压力，更不能用单一收益改善补偿回撤。', '',
              '## 累计112配置与各家族范围', '',
              f"累计415日收益门通过{summary['common_return_pass']}/112、回撤门通过{summary['common_dd_pass']}/112；联合中心通过{summary['joint_pass']}/112。完整累计行见[all_centers.csv](others/all_centers.csv)，以下每组最高收益与最低回撤可以来自不同配置，不能拼接成一条虚拟策略。", '',
              '| 家族/许可 | 退出 | 配置数 | 最高收益hold | 最高净收益 | 对应回撤 | 最低回撤hold | 最低回撤 | 对应净收益 |',
              '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for item in summary['family_summary']:
        best, low = item['best_return'], item['lowest_dd']
        lines.append(f"| {item['family']}/{item['mode']} | {item['exit_rule']} | {item['count']} | {best['parameters']['hold']} | {100*best['net_return']:.3f}% | {100*best['dd']:.3f}% | {low['parameters']['hold']} | {100*low['dd']:.3f}% | {100*low['net_return']:.3f}% |")
    best, low = summary['best_return'], summary['lowest_dd']
    lines += ['', f"累计最高收益为{best['experiment']}/{best['candidate']}，净收益{100*best['net_return']:.3f}%、回撤{100*best['dd']:.3f}%，60日频率中位{best['frequency_median']:.0f}笔，原中心门{'通过' if best['full_pass'] else '未通过'}；最低回撤为{low['experiment']}/{low['candidate']}，回撤{100*low['dd']:.3f}%、净收益{100*low['net_return']:.3f}%。这是已见开发样本的描述性极值，不是独立预测证据。", '',
              '收益/回撤前沿忽略频率，仅表示在已测配置中没有另一行收益更高且回撤更低，不能据此认定资格。原中心通过清单、完整前沿与年度/252日切片详见[累计描述汇总](others/search_summary.json)。年度为实际部分日历区间，不年化；切片继承原资金和仓位，没有重新注资，局部峰值回撤与继承历史峰值回撤分别标注。', '',
              '## 边界核对', '',
              '固定退出H≥10在当前单持仓、二元entry_cycle、无提前退出、无期末强平且无重叠子仓的规则下，由EX044代数上界排除：相邻闭合退出至少间隔H+1日；H=10时375个60日窗至多175窗能有6笔，小于中位达到6所需188窗。H≥11时无窗口能容纳6笔。因此固定整数1..9是这一必要频率条件未排除的完整域，已全覆盖；并未实际回测所有更长账户，也不能将证明推广至许可退出。', '',
              '许可退出允许提前离场，15/30是年龄上限，不能套用固定持有频率证明。以下完整列出预选B/path、B/and在7、8、9、15、30的边界；不从未测10..14、16..29或更长上限推定结论。', '',
              '| 模型/许可 | hold | 原型 | 净收益 | 回撤 | 闭合周期 | 频率中位 | ≥3笔窗口 |',
              '| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    combined = list(rows)
    for payload in protocol['controls_results']:
        combined.extend(read(EvidenceRef.from_dict(payload).resolve(ROOT))['rows'])
    boundary = [r for r in combined if r['parameters']['family'] == 'B' and r['parameters']['mode'] in ('path', 'and') and r['parameters'].get('exit_rule', 'fixed') == 'permission' and r['parameters']['hold'] in (7, 8, 9, 15, 30)]
    assert len(boundary) == 10
    for row in sorted(boundary, key=lambda r: (r['parameters']['mode'], r['parameters']['hold'])):
        p = row['parameters']; f = row['runs']['full']
        lines.append(f"| B/{p['mode']} | {p['hold']} | {row['candidate_id']} | {100*f['net_return']:.3f}% | {100*f['dd']:.3f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']}/{f['frequency_windows']} |")
    lines += ['', 'B/path许可上限15的净收益55.470%、回撤18.469%，上限30为52.474%/18.466%；30日的回撤微小变化不能遮蔽收益减少和频率覆盖仅337/375、少于338的失败。B/and上限15与30的收益/回撤相同，频率覆盖均323/375。长上限未带来达标策略，但中间整数仍应按有限界补齐，不能仅凭两个端点断言全部无效。', '',
              '阶段二独立事件允许重叠、每次重新投入10万元；连续账户共享资金、排斥重叠机会，并受成交数量、复利与费用约束。四折事件诊断与本轮历史学习日程也不同。有限组件信息用途不能直接转化为账户收益承诺，改变持有/退出是在检验构造机制，不能把本次反复使用的开发成绩称为新样本。', '',
              '## 账户与运行证据', '']
    audit = audits['account_audit.json']
    lines += [f"独立账户审计PASS：{len(audit['accounts'])}个正式场景、{audit['formal_ledger_exports_checked']}份五类账本、{audit['input_checks_count']}份输入及{audit['feature_prediction_intention_rows']}行实际特征/预测/许可/意图，逐一核对冻结模型、实际执行、净值、回撤、周期及频率。本轮运行核验与复用训练核验均PASS。", '',
              'available_cash_fraction/entry_cycle在入场时锁定周期目标数量；正意图期间可以继续尝试未完成买入，补买不另计闭合周期。意图年龄不保证等于实际持仓天数；未成交日消耗意图时钟，次日执行和实际延迟逐周期核对。末端未平仓只估值、不强制卖出。1%限价、tick/lot与涨跌幅保护、市场卖出、每侧0.1%费用、HFQ_RESEARCH与DAILY_RANGE_V3保持不变。', '',
              '本轮没有串并行技术重复；precheck_five_ledgers_equal=false表示不重做而非比较失败。EX042与EX045合计4个技术重复场景由其主运行器核对两窗五账本及hash一致，串行账本未另持久化，独立账户审计不另重跑这项比较。EX042短IDprepare技术拒绝发生在账户执行之前；本轮使用已认证完整身份修正，无新策略含义。', '',
              '毛收益分解是固定实际成交现金流加末端估值的扣费前归因，不是零手续费重跑；入场日/后续损益不是可避免损失的因果估计。技术PASS只确认实现与数值可核验。', '',
              '## 未用字段差异', '']
    sample = differences['differences'][0]; volume = sample['unused_field_differences']['Volume']
    lines += [f"实际盘中数据{sample['rows']}行中，Volume相对旧认证快照有{volume['rows']}行尾差，最大绝对差{volume['max_absolute']:.0f}、最大相对差{volume['max_relative']:.9g}。134场景记录同一底层差异，不重复算作独立变化。盘中实际使用的OHLC、Amount、AvailableDate和日线使用字段精确一致；不能宣称全字段或数据身份相同。盘中Volume未进入13特征，执行未启用成交量容量约束；56883行实际预测链已验证等价，差异原件与身份仍保留。", '',
              '## 下一步建议与交付定位', '']
    if summary['joint_pass']:
        lines += ['累计出现联合中心通过配置，应由阶段三统一交付按原目标评审其后续资格检验；不能跳过32点扰动、费用压力或必要授权，不能因本报告发布就宣布策略达标。']
    else:
        lines += ['累计尚无联合中心通过配置，当前不得交接“达标策略”。固定1..9整数域已完整覆盖，固定更长域由原频率门排除。许可退出10..14、16..29及其他家族的中间整数尚未全部测试，不能在EX046宣称该域穷尽。已安排独立EX047按各许可最长连续有效段给出的有限界补齐47个配置、94个正式账户；需其结果与边界审计完成后统一判断是否收尾，EX046的112配置汇总不随之后结果改写。']
    lines += ['', '本脚本不组装CANDIDATES、不更改研究族状态、不发布ASSESSMENT，不执行阶段四或PTE。最终CANDIDATES/5由主研究会话统一合并完整搜索和边界判断；报告与审计PASS不等于MANDATE/3策略验收通过。', '',
              '证据：[冻结协议](protocols/accounts.json)、[67配置结果](others/results.json)、[累计汇总](others/search_summary.json)、[112配置表](others/all_centers.csv)、[账户审计](others/account_audit.json)、[运行核验](others/runtime_checks.json)、[输入差异](others/input_difference_observed.json)。旧对照、模型、运行源及频率证明由协议EvidenceRef认证。']
    (HERE / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print('EX046_REPORT_READY', flush=True)


def publish():
    assert not (HERE / 'others/published_refs.json').exists(), 'Already published; never overwrite'
    result, _, _, _ = inputs()
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
    print('EX046_PUBLISHED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('report', 'publish'))
    {'report': report, 'publish': publish}[parser.parse_args().mode]()
