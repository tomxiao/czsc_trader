"""Read back signed FULL ledgers and actual audit; no new account simulation."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from math import isclose
from research_experiment import load_experiment_input, experiment_source_sha256

ROOT = Path.cwd()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', choices=['EX050_20261006', 'EX052_20261006', 'EX053_20261006', 'EX054_20261006', 'EX055_20261006'], required=True)
    parser.add_argument('--audit', required=True)
    parser.add_argument('--equivalence')
    args = parser.parse_args()
    exp = ROOT / 'experiments/S012' / args.experiment
    rex = exp / 'artifacts/rex'
    receipt, trials, binding = (read(rex / 'execution_receipt.json'), read(rex / 'trials.json'),
                                read(exp / 'experiment_binding.json'))
    load_experiment_input(rex, expected_receipt_sha256=receipt['receipt_sha256'])
    assert experiment_source_sha256(exp, tuple(binding['source_files'])) == binding['source_sha256'] == receipt['source_sha256']
    audit_path = ROOT / args.audit
    audit = read(audit_path)
    assert audit['status'] == 'PASS' and not audit['errors']
    assert audit['verified_receipt_hashes'][args.experiment] == receipt['receipt_sha256']
    assert len(trials) == len(receipt['trace']['evaluations'])
    assert all(row['record']['status'] == 'SUCCEEDED' for row in trials)
    evidence = [ref(rex / 'execution_receipt.json'), ref(rex / 'trials.json'), ref(audit_path)]
    if args.equivalence:
        path = ROOT / args.equivalence
        eq = read(path)
        assert eq['status'] == 'PASS' and eq['passed'] == len(trials) and eq['approved_for_research_comparison']
        evidence.append(ref(path))
    rows = []
    for trial in trials:
        path = rex / trial['record']['result_artifact']['path']
        assert ref(path)['sha256'] == trial['record']['result_artifact']['sha256']
        result = read(path)
        run = result['runs'][0]
        account, fills, decisions, trades = (run['ledgers'][name]['data']
            for name in ('account_daily', 'fills', 'decisions', 'trades'))
        m = trial['metrics']
        assert len(account) == len(decisions) == 1534
        assert isclose(account[-1]['equity'], m['final_equity'], abs_tol=1e-7)
        assert sum(row['status'] == 'CLOSED' for row in trades) == m['closed_trades']
        assert isclose(sum(row['fees'] for row in fills), m['total_fees'], abs_tol=1e-7)
        prior, annual = 100000., []
        for year in range(2020, 2027):
            block = [row for row in account if str(row['date']).startswith(str(year))]
            final = block[-1]['equity']
            annual.append({'year': year, 'sessions': len(block), 'ending_equity': final,
                'equity_increment': final - prior, 'net_period_return': final / prior - 1,
                'holding_session_ratio': sum(row['quantity'] > 0 for row in block) / len(block)})
            prior = final
        rows.append({'candidate_id': trial['candidate_id'], 'label': trial['control_label'],
            'parameters': trial['parameters'], 'metrics': m, 'annual': annual,
            'exit_reason_counts': dict(Counter(row['decision_reason'] for row in decisions
                                               if row['action'] == 'SELL')),
            'decision_reason_counts': dict(Counter(row['decision_reason'] for row in decisions)),
            'open_cycles': sum(row['status'] == 'OPEN' for row in trades),
            'result': ref(path), 'source_selection_ids': trial['source_selection_ids']})
    ranked = sorted(rows, key=lambda row: (-row['metrics']['net_cagr'],
        abs(row['metrics']['max_drawdown']), -row['metrics']['frequency'], row['candidate_id']))
    feasible = [row for row in ranked if row['metrics']['goals'][1] and row['metrics']['goals'][2]]
    qualified = [row['candidate_id'] for row in ranked if row['metrics']['passed_all']]
    summary = {'schema_version': 1, 'experiment_id': args.experiment, 'receipt_sha256': receipt['receipt_sha256'],
        'audit_status': 'PASS', 'accounts': len(rows), 'successful': len(rows), 'qualified': qualified,
        'best_return': ranked[0]['candidate_id'], 'best_drawdown_frequency_feasible': feasible[0]['candidate_id'] if feasible else None,
        'rows': rows, 'evidence_files': evidence, 'stage_three_complete': False, 'all_development_pool_seen': True,
        'priority': ['net_cagr_desc', 'absolute_max_drawdown_asc', 'actual_closed_frequency_desc']}
    dest = ROOT / '.tmp/s012-stage3-native-20261006/delivery-prep'
    save(dest / (args.experiment + '_full_diagnosis.json'), summary)
    text = f'# {args.experiment} 完整账户检查点\n\n'
    text += f'实际{len(rows)}组FULL全部成功，独立账户审计通过，原三个经济目标同时达标{len(qualified)}组；阶段三仍进行。'
    if args.equivalence:
        text += f'当前源码真实FULL与研究加速账本{len(rows)}组逐项一致。'
    text += '\n\n原目标为净年化≥21.4300%、回撤幅度严格<30.2906%、真实闭合周期×60/1535≥5（至少128闭合）。全部开发池已见，252/1534年化，期末开放周期排除。\n\n'
    text += '|方案|控制|净年化|回撤幅度|闭合|每60日频率|费用/元|持仓会话比|三门|\n|---|---|---:|---:|---:|---:|---:|---:|---|\n'
    for row in rows:
        m = row['metrics']
        text += f"|{row['candidate_id']}|{row['label']}|{m['net_cagr']:.4%}|{abs(m['max_drawdown']):.4%}|{m['closed_trades']}|{m['frequency']:.4f}|{m['total_fees']:.2f}|{m['exposure']:.4%}|{m['goals']}|\n"
    if args.experiment == 'EX050_20261006':
        text += '\n原两条搜索前沿C4600/4601及溢价2%邻居C4603与原筛选复现。C4604机会消失退出提高闭合次数但明显降低净年化；C4605/4606动量状态入场或同时退出均降低净年化且频率未达，不作为默认强制门。C4607峰值退出较C4601净年化提高约0.1872个百分点，回撤幅度增加；原回撤门仍通过，保留收益改善及其代价。\n\n后继检验三组冷却对照、mom未知政策单项配对，以及2%限价和5%峰值退出联合。原三硬门保持，收益优先；联合效果尚未发生，不预判改善。净年化15.1116%的前沿距收益门约6.3184个百分点；有限小幅执行改善未解决收益差距。\n'
    text += '\n年度、实际费用、退出原因、期末开放状态及原参数来源见紧凑诊断。持仓会话比是持股日期比例；年度权益连续、不重置账户。所有失败与反面结果保留。技术PASS表达复算一致，经济门按原合同独立判断，稳定性与年度集中只作诊断。\n\n'
    text += f"完整回执：`{receipt['receipt_sha256']}`。真实账户及制品在本机`artifacts/rex/`，策略与特征源码按绑定闭包保存；Git不包含全部DFLS和REX制品。\n"
    report = dest / (args.experiment + '_04_conclusion.md')
    with report.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print(json.dumps({'status': 'PASS', 'experiment_id': args.experiment, 'accounts': len(rows),
                      'qualified': qualified, 'report': ref(report)}))


if __name__ == '__main__':
    main()
