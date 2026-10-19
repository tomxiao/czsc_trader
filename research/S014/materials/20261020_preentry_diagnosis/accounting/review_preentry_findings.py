"""Independent checks against existing CLOSED trades, and bounded readout."""
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
CHECKS = Counter()


def check(name, value):
    assert value, name
    CHECKS[name] += 1


def read(name):
    return json.loads((OUT / name).read_bytes())


def table(name):
    with (OUT / name).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def save(name, value):
    path = OUT / name
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8') if not isinstance(value, str) else value.encode('utf-8')
    if path.exists():
        check('frozen output equal', path.read_bytes() == content)
    else:
        path.write_bytes(content)
    return ref(path)


def main():
    summary = read('preentry_accounting_summary_v2.json')
    evidence = EvidenceRef.from_dict(summary['source_account_ref'])
    content = evidence.resolve(ROOT).read_bytes()
    check('account exact SHA', sha256(content).hexdigest() == evidence.sha256)
    account = json.loads(content)
    ledgers = account['runs'][0]['ledgers']
    closed = {r['cycle_id']: r for r in ledgers['trades']['data'] if r['status'] == 'CLOSED' and r['exit_date'][:10] <= '2025-12-31'}
    fills = {r['cycle_id']: r for r in ledgers['fills']['data'] if r['side'] == 'BUY'}
    sales = {r['cycle_id']: r for r in ledgers['fills']['data'] if r['side'] == 'SELL'}
    cycles = table('preentry_actual_cycles_v2.csv')
    rows = table('preentry_actual_attempts_v2.csv')
    for cycle in cycles:
        cid = cycle['cycle_id']
        buy = fills[cid]
        if cycle['cycle_status'] != 'CLOSED_BY_2025_CAP':
            check('censored never certified closed asof cap', cid not in closed)
            continue
        trade, sell = closed[cid], sales[cid]
        check('actual complete cycle dates', cycle['entry_E'] == trade['entry_date'][:10] and cycle['exit_E'] == trade['exit_date'][:10])
        check('reported original trade return matches derived money return', abs(float(cycle['cycle_net_return_to_cap']) - trade['net_return']) <= 1e-12)
        per_unit = sell['price'] * .999 - buy['price'] * 1.001
        net_money = sell['quantity'] * sell['price'] - sell['fees'] - buy['quantity'] * buy['price'] - buy['fees']
        check('actual funded strictly positive quantity', buy['quantity'] == sell['quantity'] and buy['quantity'] > 0)
        sign = lambda x: -1 if x < 0 else 1 if x > 0 else 0
        check('perunit money original trade exact sign agreement', sign(per_unit) == sign(net_money) == sign(trade['net_return']) == sign(float(cycle['cycle_net_pnl_to_cap'])))
    for row in rows:
        D = row['D']
        prior = sorted((r for r in closed.values() if r['exit_date'][:10] <= D), key=lambda x: x['exit_date'])
        check('prior completed count original trades', int(row['known_closed_cycles']) == len(prior))
        check('no future completed history', not prior or prior[-1]['exit_date'][:10] <= D < row['E'])
        check('prior cycle identity original trade', row['previous_closed_cycle_id'] == (prior[-1]['cycle_id'] if prior else ''))
        expected = 'NO_PRIOR_CLOSED' if not prior else 'PREVIOUS_NET_LOSS' if prior[-1]['net_return'] < 0 else 'PREVIOUS_NET_PROFIT' if prior[-1]['net_return'] > 0 else 'PREVIOUS_EXACT_ZERO'
        check('prior sign original funded trade', row['prior_closed_group'] == expected)
        streak = 0
        for trade in reversed(prior):
            if trade['net_return'] >= 0:
                break
            streak += 1
        check('loss streak original funded trades', int(row['known_consecutive_closed_losses']) == streak)
        if row['filled'] == 'False':
            check('failed BUY no invented cycle outcome', row['cycle_net_return_to_cap'] == row['cycle_net_pnl_to_cap'] == row['actual_entryday_net_pnl'] == row['actual_E_fill_price'] == '')
    groups = table('preentry_prior_group_v2.csv')
    years = table('preentry_yearly_v2.csv')
    by_D = {r['D']: r for r in rows}
    case_dates = ['2024-01-26', '2024-04-09', '2024-04-24', '2024-07-12', '2024-10-08', '2024-10-23', '2024-12-24',
                  '2021-02-03', '2021-12-08', '2025-05-29']
    cases = [{k: by_D[D][k] for k in ['D', 'E', 'cycle_id', 'previous_closed_exit_E', 'prior_closed_group', 'known_consecutive_closed_losses',
                                             'D_support_distance_atr', 'D_z5', 'actual_E_trigger_POSTHOC', 'Dclose_to_fill_return',
                                             'fill_to_Eclose_return', 'actual_entryday_net_pnl', 'cycle_net_return_to_cap']} for D in case_dates]
    findings = {
        'status': 'PASS_ACCOUNT_ONLY_DIAGNOSIS', 'source_account_ref': summary['source_account_ref'],
        'scope': 'EX044004 original funded account; D and actual E through 2025 only. No new strategy execution or counterfactual wealth.',
        'implementation': ref(Path(__file__).resolve()), 'extraction': ref(OUT / 'preentry_accounting_summary_v2.json'),
        'prior_sign_groups': groups, 'yearly_entry_attribution': years,
        'findings': [
            {'claim': 'Loss-following entries are not generally the more dangerous group in this existing account.',
             'evidence': 'Entryday losses 28/68 after a completed loss vs27/53 after a completed profit; 67/53 closed next cycles mean net return +2.59118253%/+0.27345113%. Each of the six annual closed-next-cycle means is higher after a loss than after a profit.',
             'limit': 'Observational original path; unequal populations, economic regimes and capital. Not causal skip-policy return.'},
            {'claim': '2024 does not reverse that negative directional evidence.',
             'evidence': 'After loss13 filled entries net entryday PnL -28438.306; after profit8 -34028.867. Mean fill-to-close -0.50495219%/-0.98681301%; closed cycle means -0.03577505%/-2.02942198%.',
             'limit': 'Counts and means are report-only, not a new economic acceptance gate.'},
            {'claim': '2024 damage mostly occurs after actual entry; overall higher execution price relative to D is not the sufficient explanation.',
             'evidence': '21 entries actual fill-to-Eclose gross -54691, buy fees7776.173, actual net -62467.173. Aggregate Q*(fill-Dclose)=-12214, a price bridge not booked pre-entry PnL.20 OPEN entries gross -47331 vs1 DAILY_LIMIT entry -7360.',
             'limit': 'OPEN/DAILY_LIMIT and E close are E-known attribution. They cannot be a D-entry filter. No order-price contract alteration is evaluated.'},
            {'claim': 'A continuous-loss explanation has strong actual rebound counterexamples.',
             'evidence': '2024Apr25 entry after2 completed losses: full actual net return+22.75166694%; 2021Feb4 after2 losses+39.93723668%;2021Dec9 after4 losses+21.90359976%.2025May30 after2 losses loses1.953125% fill-to-entryday-close yet earns+23.58071616% over its actual whole cycle.',
             'limit': 'Do not replace full-cycle/account value with an entryday loss indicator or retrospectively delete a losing entry.'},
            {'claim': 'Known support distance is an explanatory rival, not a newly discovered cutoff.',
             'evidence': '2024DJan26 supportdistance1.552ATR precedes entryday -3.48584%; DOct8 distance8.350ATR precedes -8.06100%. DApr24 distance0.234ATR precedes a+22.7517% full cycle; DDec24 distance0.0288ATR precedes-6.02315%.',
             'limit': 'No support/ATR threshold scan, fit or combined rule was performed. Examples show one threshold is not justified by these cases.'},
            {'claim': 'Original population retains missing and unfinished economic outcomes.',
             'evidence': '125 intents=122 fills+3 failed BUY;121 actual closed cycles+1 open2025Dec23 cycle marked throughDec31, no exit fee. Failed intents have null entryday/cycle outcomes; exact-zero prior group has0 observations.',
             'limit': '2026 later actual exit is not used. The open2025 cycle is not a completed loss for any2025 D.'}
        ],
        'selected_existing_cases': cases,
        'root_proposal_state_review': {
            'proposal_ref': ref(OUT.parent / 'design_proposal.json'),
            'status': 'D_INFORMATION_FEASIBLE_NOT_ECONOMIC_ENDORSEMENT',
            'requirements': ['Fresh BASE must exactly reproduce EX044004.',
                             'Each active profile uses its own actual completed funded cycles and actual both-side fees; original-path prior groups are descriptive only.',
                             'Actual SELL at D open may become D-close information; sell intention/pending and marked losses never count as completion.',
                             'One armed event consumed only once at original eligible flat D; virtual reservation creates no position, entry, fee or completed trade.',
                             'Failed BUY is not a cycle or net-loss event. Do not condition a pause on whether future E would fill.',
                             'Own-year capital return, all original hard goals, full funded path and opposite-sign control determine outcomes; do not infer active results by subtracting original trade PnL.'],
            'directional_caveat': 'Current observations weaken the loss-specific direction. Keeping the earlier fixed loss/profit contrast is a mechanism test, not confirmation that loss pause is favored.'},
        'checks': dict(CHECKS), 'check_count': sum(CHECKS.values()),
        'resources': {'new_accounts': 0, 'new_replays': 0, 'fits': 0, 'market_calls': 0, 'prepared_fetches': 0},
        'next_step': 'Only locked fixed full-path policy contrast can evaluate pause value; do not search a better loss-streak/support threshold from these tables.'}
    result = save('preentry_research_findings.json', findings)
    readout = '''原EX044成本止损账户的只读诊断已完成；当前事实削弱“亏损后下一笔更危险”的方向假设。

2020–25共有125次真实买入意图：122次成交、3次未成交；121笔周期实际闭合，2025年12月23日最后一笔仅估值到12月31日。未成交收益为空，末仓不虚构退出费，也不读取2026后来退出收益。

上一笔实际净亏后，68次成交有28次入场日净亏；上一笔净盈后，53次成交有27次。后续实际闭合周期平均净回报为2.5912%与0.2735%；六个自然年逐年比较也都是亏损后组均值更高。这是原路径关联，不是“跳过亏损后机会”的财富回报。

2024同样不是亏损后更坏：13笔亏损后入场净损28438.306，8笔盈利后入场净损34028.867；成交到当日收盘平均跌0.5050%与0.9868%。连续两次亏损后，2024年4月25日那笔完整交易仍净赚22.75%；2021年2月4日净赚39.94%。2025年5月30日那笔买后首日跌1.95%，整个实际周期却净赚23.58%，说明首日伤害不能代替完整持仓价值。

2024入场日实际毛损54691，买费7776.173，合计净损62467.173。D收盘到成交价的数量加权价差为负12214，即总体成交价更低；该价差只是价格桥接，不是买入前账户已赚的钱。20次开盘成交毛损47331，唯一盘中限价成交毛损7360；损伤主要不是盘中触发这一小类。成交类别和E收盘在D下单时都未知。

支持位距离在D可知，仍有竞争解释价值；本轮没有为它寻找阈值。较远的2024年1月26日、10月8日后续入场受损，较近的4月24日后周期大赚，12月24日后又亏损，不能凭个例设定单一边界。

下一步按已固定的BASE／亏损后暂停一轮／盈利后暂停一轮完整账户对照，检验暂停是否只是重新安排了参与时间。每条新路径须用自己的真实完成史、资金与年度开端，保留失败买入和反例；全部历史已见，不称样本外。

数据、逐笔事实和核验入口见 preentry_accounting_summary_v2.json、preentry_actual_attempts_v2.csv 与 preentry_research_findings.json。初版保留，v2仅将没有实际成交或闭合周期的分组结果明确为空。
'''
    print(json.dumps({'findings': result, 'readout': save('preentry_readout.md', readout), 'checks': findings['check_count']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
