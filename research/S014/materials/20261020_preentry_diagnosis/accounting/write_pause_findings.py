"""Bounded interpretation of frozen actual-account outputs, no new runs."""
import csv
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent


def ref(name):
    path = OUT / name
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def table(name):
    with (OUT / name).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def save(name, value):
    path = OUT / name
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n') if not isinstance(value, str) else value
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    return ref(name)


def main():
    summary = json.loads((OUT / 'independent_pause_audit_summary.json').read_bytes())
    policies = {r['pause_profile']: r for r in summary['policy_summary']}
    annual = table('pause_policy_yearly_summary.csv')
    attribution = table('pause_entryday_yearly_attribution.csv')
    names = ['BASE', 'AFTER_NET_LOSS_SKIP1', 'AFTER_NET_PROFIT_SKIP1']
    by_year = {(r['pause_profile'], int(r['year'])): r for r in annual}
    loss = policies[names[1]]
    assert loss['nannual_return_pass_2020_25'] == loss['nannual_drawdown_pass_2020_25'] == 6
    assert loss['nannual_return_pass_original_full_contract'] == 6 and loss['nannual_drawdown_pass_original_full_contract'] == 7
    assert loss['original_frequency_pass']
    refs = [ref(n) for n in ['independent_pause_audit_summary.json', 'pause_policy_yearly_summary.csv', 'pause_policy_summary.csv',
                            'pause_entryday_yearly_attribution.csv', 'pause_entryday_attribution_review.json', 'preentry_research_findings.json',
                            'pause_original_mandate_clarification.json']]
    findings = {
        'status': 'COMPLETE_FIXED_ACCOUNT_CONTRAST_NOT_ALL_ORIGINAL_GOALS_ACHIEVED',
        'sources': refs, 'implementation': ref(Path(__file__).name),
        'summary': 'Loss-conditioned one-shot pause reaches original targets in all six complete2020-25 years and original frequency, but original partial2026 annual hard gate is retained: originalfullcontract return6/7,DD7/7, not qualified.',
        'all_original_economic_goals_achieved': False,
        'facts': [
            {'finding': 'LOSS policy is real full-funded progress, not deletion of original losing trades.',
             'proof': 'Source5e77 all fixed rules; actual completion-net sign, own funded cycle/fees and one-shot clock verified. 2020-25 returns4.251139%,150.738961%,5.119859%,8.532731%,20.251379%,47.031981%; fullfrequency92/1642*60=3.36175396.',
             'limit': 'No new heldout sample; history already used in earlier structural research.'},
            {'finding': '2024 improvement includes entry damage reduction and larger post-entry path contribution.',
             'proof': 'Own-opening entryday net -17.53706603pp BASE vs-4.00744793pp LOSS: +13.52961810pp. Postentry actual hold/sell minus sellfees +5.16461108pp vs+24.25882724pp: +19.09421617pp. Sum+32.62383426pp equals annual return difference.',
             'limit': 'Own populations/capital differ. This is an accounting identity, not a causal attribution of skipped original trades or pure predictive-information value.'},
            {'finding': 'The opposite-sign pause also fixes2024 but fails2025.',
             'proof': 'PROFIT2024+19.56693589%,2025-2.85082992%;2024 entryday net+2.47035543pp, better than LOSS entryday contribution while its later yearly performance is worse.',
             'limit': '2024 success alone cannot distinguish loss information from changed participation dates; two directions have different doses/populations.'},
            {'finding': 'Strong adverse years and opportunity costs remain visible.',
             'proof': 'LOSS2020 falls from BASE35.593161% to4.251139% (-31.342022pp),2023 from17.28835493% to8.53273123% (-8.75562370pp). It still meets those original yearly gates; no new nonharm veto.',
             'limit': 'Do not describe improvement as consistent outperformance every year.'},
            {'finding': 'Earlier observational counterevidence is not discarded.',
             'proof': 'Original cost population after-loss closed next cycles had higher mean return than after-profit in each of six years; Apr25/2024 after two losses +22.75%, May30/2025 entryday negative but fullcycle+23.58%.',
             'limit': 'Successful new dynamic policy does not prove original loss-following entries were systematically more dangerous or identify linear signal-vs-clock shares.'},
            {'finding': 'Without2025 improvement and retained partial-year mandate are distinct claims.',
             'proof': 'End2024 equity LOSS358623.049 vsPROFIT337723.059 vsBASE312130.034; end2025 equity527290.572/328095.149/439233.764 respectively. Original full-contract count remains LOSS6/7 annualreturn,7/7DD; no new2026 detail selection.',
             'limit': 'Complete-year success does not amend original acceptance; no historical eligibility, registration or promotion changed.'}
        ],
        'fixed_policy_outcomes': list(policies.values()),
        '2024_actual_phase_attribution': [r for r in attribution if r['year'] == '2024'],
        'one_shot_slots_2020_25': {p: sum(v['pause_slot_consumed'] for v in years.values()) for p, years in summary['profile_lifecycle_counts'].items()},
        'distinct_funded_2020_25_paths': len(summary['funded_path_equivalence_classes_2020_25']),
        'resources': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'],
        'technical_record': 'One original internal D/E expression incident corrected by additive helper and same-account supplementary audit; no account rerun. One local-publication auto-review rejection then destination-proof approval, retained separately. No change to prices, fees, tolerances, source or original criteria.',
        'next_step': 'Preserve this full-path research result and explain the remaining original acceptance gap. Root/user decides any next research stage; no extra profile or2026 tuning in this round.'}
    finding_ref = save('pause_research_findings.json', findings)
    labels = dict(zip(names, ['成本止损基线', '亏损后暂停一轮', '盈利后暂停一轮']))
    lines = ['亏损后暂停一轮取得明确进展，但尚未通过全部原验收。\n',
             '2020–25六个完整自然年的收益与回撤要求均通过，原全窗口交易频率也通过。原合同仍包括2026截至10月15日的部分年，不年化；全合同收益为6/7、回撤7/7，不能改写为所有目标已达成，也不改变历史资格。2026不用于本轮挑选规则，不代表从原门中删除。\n',
             '|年份|成本止损基线|亏损后暂停一轮|盈利后暂停一轮|\n|---|---:|---:|---:|']
    for year in range(2020, 2026):
        values = [float(by_year[(p, year)]['return']) * 100 for p in names]
        lines.append(f'|{year}|' + '|'.join(f'{v:.2f}%' for v in values) + '|')
    lines += ['\n亏损后暂停的原全窗口真实闭合92笔，频率3.3618次/60日（要求至少3）；完整2020–25闭合80笔。2025末权益527290.572，年初358623.049；末仓88000研究单位、现金4570.572，保留未平仓估值，不虚构末日卖出费。三条路径不同，控制账户只是精确重复原成本基线，不是新增独立验证样本。\n',
              '2024不是只靠买入当日避损：基线21次实际入场，入场毛损54691、买费7776.173，净损62467.173；亏损后暂停13次实际入场，毛损7231、买费4720.324，净损11951.324。按各自年初资金，入场日净贡献改善13.5296个百分点，后续持有和实际卖出扣卖费贡献改善19.0942个百分点，合计等于全年32.6238个百分点的改善。后者更大，且资金与机会人口已改变，不能解释成单纯买前预测或删掉旧亏损交易的因果收益。\n',
              '反证保留：盈利后暂停也让2024转正到19.57%，其入场日净贡献甚至更好，但2025亏损2.85%。亏损后暂停在2020少赚31.34个百分点、2023少赚8.76个百分点；仍满足当年原门，不另加“各年必须不劣于基线”的否决条件。原人口中亏损后反弹的Apr25/2024、May30/2025等案例也不撤销；新账户结果并不证明“亏损后本来就更危险”。\n',
              '全部2020–25都属已见开发历史。剔除2025后的2024末权益：亏损后暂停358623.049、盈利后暂停337723.059、基线312130.034；这支持改善不只依赖2025，但不是独立样本外验证。\n',
              '资源与技术：3次真实派发均执行成功，0执行失败、0未知、0重派、0拟合、0新增市场调用；独立实际账户764985项核验通过。保留1次内部D/E审核表达失败，并以同一账户的后继审核修正；拒绝的本地保存操作经目的地证明获准后完成，记录同样保留。未改策略、参数、费用、容差、原验收或历史资格。\n',
              '下一步先完成本轮留证与目标差距说明，再由主会话和用户决定后续研究；本轮不追加规则或按2026细节调参。\n',
              '证据入口：[总审](independent_pause_audit_summary.json)、[逐年表](pause_policy_yearly_summary.csv)、[实际入场归因](pause_entryday_yearly_attribution.csv)、[原合同边界](pause_original_mandate_clarification.json)。\n']
    readout_ref = save('pause_readout.md', '\n'.join(lines))
    print(json.dumps({'findings': finding_ref, 'readout': readout_ref, 'profiles': labels}, ensure_ascii=False))


if __name__ == '__main__':
    main()
