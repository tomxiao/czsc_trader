"""Publish a user-added constraint and reassess existing immutable results."""
from dataclasses import replace
from hashlib import sha256
import json
import math

import pandas as pd

from czsc_trader.application import assemble_delivery, publish_evidence, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT, context, save, SRC
from economics import annual_stats


def read_content(stage, revision):
    path = ROOT / f'research/S013/assets/deliveries/{stage}/{revision}/delivery.json'
    return d.DeliveryContent.from_dict(json.loads(path.read_text(encoding='utf-8'))['content'])


def reference(stage, revision):
    path = ROOT / f'research/S013/deliveries/{stage}/{revision}/receipt.json'
    return d.DeliveryReceipt.from_dict(json.loads(path.read_text(encoding='utf-8'))).reference


def evaluate_constraint(annual, benchmark):
    assert set(annual) == set(benchmark) == {str(y) for y in range(2020, 2027)}
    checks = {}
    for year, by in benchmark.items():
        sy = annual[year]
        assert by['sessions'] == sy['sessions']
        assert all(math.isfinite(x['return']) for x in (by, sy))
        triggered = by['return'] < 0
        checks[year] = {
            'buyhold_net_return': by['return'], 'strategy_net_return': sy['return'],
            'triggered': triggered, 'passed': not triggered or sy['return'] > 0,
            'sessions': sy['sessions'],
        }
    return checks, all(c['passed'] for c in checks.values())


def main():
    research = context()
    experiment = ExperimentRef('S013', 'EX004_20261007')
    old_mandate = read_content('MANDATE', 3)
    old_candidates = read_content('CANDIDATES', 1)
    old_candidate_ref = reference('CANDIDATES', 1)
    old_mandate_ref = reference('MANDATE', 3)
    published_rows = next(x for x in old_candidates.evidence if x.name == 'hfq-search-results')
    rows = json.loads(published_rows.resolve(ROOT).read_text(encoding='utf-8'))['rows']
    valid = [r for r in rows if r['status'] == 'SUCCEEDED']
    assert len(valid) == len({r['config_hash'] for r in valid}) == 378
    assert sum(r['status'] == 'UNKNOWN' for r in rows) == 16
    trial_years = {str(y): {'sessions': 243, 'return': 0.1} for y in range(2020, 2027)}
    negative = {**trial_years, '2022': {'sessions': 243, 'return': -0.1}}
    zero = {**trial_years, '2022': {'sessions': 243, 'return': 0.0}}
    positive = {**trial_years, '2022': {'sessions': 243, 'return': 1e-12}}
    assert not evaluate_constraint(zero, negative)[1]
    assert evaluate_constraint(positive, negative)[1]
    assert evaluate_constraint(negative, zero)[1]

    def material(name, value):
        content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        return publish_evidence(research, MaterialEvidenceWrite(
            experiment, name, content, 'application/json', 'json'))

    confirmation = material('negative-benchmark-year-user-confirmation', {
        'date': '2026-10-08', 'source': '本主会话用户原文',
        'constraint_message': '增加一个研究的约束：在buyhold基准收益为负的年份，策略的收益必须>0',
        'annual_display_message': '算了，还是按自然年计算比较合适。应该优先对比策略与基准',
        'scope': '本次应用于S013研究约定和既有候选复核；未修改其他批次或研究员默认约束',
        'strictness': 'BuyHold年度实际净收益<0时触发；策略同年度实际净收益必须>0，等于0也不通过',
        'unchanged': '原有整体净年化、逐年回撤、平均交易频率、价格单位、费用、期间及执行要求保持',
        'stage_four': '尚未获批，未执行',
    })
    statement = ('按自然年实际扣费后净收益比较：若同年BuyHold收益<0，策略收益必须严格>0；'
                 '收益为0不满足。账户跨年连续，各年起点为上一年末权益，2020年从初始资金开始；'
                 '2026年沿用截至9月30日的期间。收益使用同标的、后复权研究单位、费用、日历和窗口。'
                 'BuyHold收益>=0的年份不触发本项，其他三项目标仍同时要求满足。')
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation)
    new_item = d.MandateItem('positive_return_in_negative_buyhold_year',
                            d.MandateItemKind.CONSTRAINT, statement, confirmed)
    mandate_report = old_mandate.report.replace(
        '# S013研究约定修订三：后复权研究账户',
        '# S013研究约定修订四：基准亏损年份策略须盈利') + '\n\n' + (
        '## 2026-10-08新增约束\n\n' + statement + '\n\n'
        '用户要求年度展示优先并列策略与基准，使用自然年实际净收益；整体开发池净年化仍按已确认的252交易日年化口径核验。'
        '新增条件由研究员按关联计算代码复核，严格不等号不编码为含零的区间要求。'
        '本修订保留MANDATE/3和旧候选结论原件；本次不开展新参数搜索，也不进入阶段四。\n'
        f'\n[新增要求确认依据](../../../assets/deliveries/MANDATE/4/{confirmation.path})\n')
    mandate_receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.MANDATE, 4, (old_mandate_ref,)),
        d.DeliveryContent(d.ResearchMandate((*old_mandate.payload.items, new_item)),
            d.DeliveryStatus.COMPLETE, (), (), report=mandate_report,
            evidence=tuple(dict.fromkeys((*old_mandate.evidence, confirmation)))))
    mandate_check = validate_delivery(research.repository, mandate_receipt.reference)
    assert mandate_check.status is d.ValidationStatus.PASS, mandate_check.to_dict()
    save('mandate_r4_reference.json', mandate_receipt.reference.to_dict())
    save('mandate_r4_validation.json', mandate_check.to_dict())

    reviewed = []
    for row in valid:
        checks, passed = evaluate_constraint(row['annual'], row['buyhold_annual'])
        old_gates = row['gates']
        assert row['qualified'] == all(old_gates.values())
        reviewed.append({
            'candidate_id': row['candidate_id'], 'config_hash': row['config_hash'],
            'content_sha256': row['content_sha256'], 'request_hash': row['request_hash'],
            'result_hash': row['result_hash'], 'annual_checks': checks,
            'old_gates': old_gates, 'old_qualified': row['qualified'],
            'negative_buyhold_year_profit_passed': passed,
            'all_four_qualified': row['qualified'] and passed,
        })
    by_id = {r['candidate_id']: r for r in reviewed}
    ledger_verifications, entries = [], []
    # Recalculate every formally retained candidate from immutable public ledgers.
    for entry in old_candidates.payload.candidates:
        identifier = entry.identity.key.candidate_id
        assert len(entry.evaluations) == 1
        ref = entry.evaluations[0].evidence
        value = json.loads(ref.resolve(ROOT).read_text(encoding='utf-8'))
        run = value['runs'][0]
        initial = value['request_identity']['initial_cash']
        own = annual_stats(pd.DataFrame(run['ledgers']['account_daily']['data']), initial)
        bh = annual_stats(pd.DataFrame(run['buyhold']['account_daily']['data']), initial)
        checks, passed = evaluate_constraint(own, bh)
        for year in checks:
            expected = by_id[identifier]['annual_checks'][year]
            assert checks[year]['sessions'] == expected['sessions']
            assert checks[year]['triggered'] == expected['triggered']
            assert checks[year]['passed'] == expected['passed']
            for key in ('strategy_net_return', 'buyhold_net_return'):
                assert math.isclose(checks[year][key], expected[key], rel_tol=0, abs_tol=1e-12)
        failed_years = [y for y, c in checks.items() if not c['passed']]
        ledger_verifications.append({'candidate_id': identifier, 'account_evidence': ref.to_dict(),
            'request_hash': value['request_hash'], 'result_hash': value['result_hash'],
            'annual_checks': checks, 'matches_published_search': True})
        decision = ('新增约束通过；' if passed else
                    '新增约束未通过：' + '、'.join(failed_years) + '年基准亏损且策略收益未严格大于0；')
        other = [k for k, passed in by_id[identifier]['old_gates'].items() if not passed]
        decision += '原三项全部通过' if not other else '原三项未满足：' + '、'.join(other)
        entries.append(replace(entry, judgment=decision))

    qualified = [r['candidate_id'] for r in reviewed if r['all_four_qualified']]
    old_ids = [r['candidate_id'] for r in reviewed if r['old_qualified']]
    gate_ids = [r['candidate_id'] for r in reviewed if r['negative_buyhold_year_profit_passed']]
    negative_years = [y for y, s in valid[0]['buyhold_annual'].items() if s['return'] < 0]
    review = {
        'source_delivery': old_candidate_ref.to_dict(), 'source_rows_evidence': published_rows.to_dict(),
        'mandate': mandate_receipt.reference.to_dict(), 'constraint': statement,
        'method': '条件触发使用自然年净收益<0；通过要求严格>0；未舍入浮点值比较；账户跨年连续',
        'successful_configuration_count': len(valid), 'unknown_attempt_count': 16,
        'negative_buyhold_years': negative_years, 'old_qualified_ids': old_ids,
        'new_constraint_pass_ids': gate_ids, 'all_four_qualified_ids': qualified,
        'configuration_checks': reviewed, 'formal_ledger_verifications': ledger_verifications,
        'new_strategy_evaluations': 0,
        'boundary_checks': ['基准负收益、策略零收益拒绝', '基准负收益、策略1e-12正收益通过',
                            '基准零收益不触发新增条件'],
        'limits': '针对新增约束的搜索尚未开展；非正式保留配置复核使用已发布统计，14个保留候选另从完整账本独立复算；原实验的样本复用和数据限制保持',
    }
    save('negative_benchmark_year_review.json', review)
    review_ref = material('negative-benchmark-year-constraint-review', review)
    method_ref = material('negative-benchmark-year-calculation-source', {
        'filename': 'review_negative_benchmark_years.py',
        'source': (SRC / 'review_negative_benchmark_years.py').read_text(encoding='utf-8'),
        'source_sha256': sha256((SRC / 'review_negative_benchmark_years.py').read_bytes()).hexdigest(),
        'platform_changes': '无', 'new_data_or_dependencies': '无',
    })
    save('negative_benchmark_year_review_reference.json', review_ref.to_dict())
    report = ['# S013阶段三修订二：新增基准亏损年份盈利约束', '',
        f'用户新增约束后，已评价{len(valid)}个不同配置中，同时满足全部四项要求的配置为{len(qualified)}个。原六个达标候选均不再满足新约定。', '',
        '## 当前约束与比较口径', '', statement, '',
        '原要求保持：完整开发池净年化≥1.5×BuyHold（门槛10.8342%），逐自然年最大回撤幅度严格更小，开发池平均每60交易日闭合交易数≥4（1636日至少110笔）。四项同时核验。', '',
        '自然年比较使用实际净收益；全开发池年化口径保持。2026年只计算至9月30日。零收益不满足新增约束；不按展示百分比的舍入值判断。', '',
        '## 原六个达标候选与基准', '',
        '| 年份 | BuyHold净收益 | C0371 | C0384 | C0385 | C0386 | C0387 | C0392 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for year in negative_years:
        cells = [f'{valid[0]["buyhold_annual"][year]["return"]:.4%}']
        cells += [f'{by_id[key]["annual_checks"][year]["strategy_net_return"]:.4%}' for key in old_ids]
        report.append('| ' + ' | '.join([year, *cells]) + ' |')
    report += ['', '两年策略与BuyHold均亏损。回撤较小不能代替策略年度盈利，因此六个候选的新增约束均不通过，新的阶段四交接集合为空。原候选登记、源码、账户和CANDIDATES/1原件保持。', '',
        '## 既有搜索复核与证据', '',
        f'仅满足新增条件的配置有{len(gate_ids)}个：' + '、'.join(gate_ids) + '。它们均未同时满足原三项要求，不能作为四项达标候选。', '',
        '复核从已发布并核对哈希的完整搜索统计读取378个成功配置；16次UNKNOWN不计入成功。14个正式保留候选另外从不可变完整账户账本重算各年收益，并核对搜索统计，差异容差1e-12；严格大于零的判断使用原始数值。没有新增策略评价、刷新行情、改变源码、费用或参数，也没有修改其他研究批次。', '',
        '新增约束是在原搜索完成后提出，旧搜索未按新条件定向设计。当前零达标只说明已检验配置集合的结果，不能据此断言不存在满足四项要求的策略。', '',
        '整个开发池已用于研究和选择；本修订没有引入独立样本。原数据异常核验、复权因子历史可得性、信号锚点与实际成交差异等限制继续适用。', '',
        '## 下一步建议', '',
        '暂不进入阶段四。建议继续阶段三，先分析2022、2023亏损交易及新增约束通过但原目标未通过的配置，形成风险规避或反向收益机制的可证伪假设，再事前声明对照方案和搜索域；若现有组件不足，提出回退阶段二的依据。新增数据、依赖或平台修改仍需相应授权。', '',
        '本次约束更新与既有结果复核已经完成；针对新约束的机制研究和搜索尚未开展，等待用户决定下一步。', '',
        '## 关联证据', '',
        f'- [用户确认](../../../assets/deliveries/CANDIDATES/2/{confirmation.path})', f'- [逐配置条件复核及账本复算](../../../assets/deliveries/CANDIDATES/2/{review_ref.path})',
        f'- [计算源码](../../../assets/deliveries/CANDIDATES/2/{method_ref.path})', f'- [原搜索统计](../../../assets/deliveries/CANDIDATES/2/{published_rows.path})']
    searches = tuple(replace(s,
        selection='本次按新增约束复核原结果，交接只保留全部四项同时通过的配置；没有新增搜索评价',
        limitations=(*s.limitations, '原搜索依旧三项目标设计；新增约束在搜索完成后提出，定向优化尚未开展'))
        for s in old_candidates.payload.searches)
    payload = d.CandidateSet(tuple(entries), (), searches,
        '新增约束下无同时达标配置；原六个交接候选不再达标，建议继续阶段三机制研究。')
    facts = (
        d.FactValue('qualified_count', len(qualified), '个配置', d.FactStatus.AVAILABLE, (review_ref,)),
        d.FactValue('new_constraint_pass_count', len(gate_ids), '个配置', d.FactStatus.AVAILABLE, (review_ref,)),
    )
    candidate_receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 2,
                             (mandate_receipt.reference, old_candidate_ref)),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, facts, (),
            report='\n'.join(report) + '\n',
            evidence=(confirmation, review_ref, method_ref, published_rows)))
    checked = validate_delivery(research.repository, candidate_receipt.reference)
    assert checked.status is d.ValidationStatus.PASS, checked.to_dict()
    save('stage3_r2_reference.json', candidate_receipt.reference.to_dict())
    save('stage3_r2_validation.json', checked.to_dict())
    print(json.dumps({'mandate': mandate_receipt.reference.to_dict(),
        'mandate_validation': mandate_check.to_dict(), 'candidates': candidate_receipt.reference.to_dict(),
        'candidate_validation': checked.to_dict(), 'negative_years': negative_years,
        'constraint_passed': len(gate_ids), 'qualified': len(qualified)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
