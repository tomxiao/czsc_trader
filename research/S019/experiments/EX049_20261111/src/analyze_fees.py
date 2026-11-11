"""Interpret paired fees using complete public account evidence and normalized cycles."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
from fee_ledger import ledger


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def stripped(value):
    return {k:v for k,v in value.items() if k not in ('sessions','daily_returns')}


def paired_cycles(standard,pressure):
    left = {r['entry_at']:r for r in standard['cycles']}
    right = {r['entry_at']:r for r in pressure['cycles']}
    common = sorted(set(left)&set(right))
    records = [{'entry_at':t,'standard_exit':left[t]['exit_at'],'pressure_exit':right[t]['exit_at'],
                'standard_pnl_over_entry_equity':left[t]['pnl_over_entry_equity'],
                'pressure_pnl_over_entry_equity':right[t]['pnl_over_entry_equity'],
                'normalized_pnl_delta':right[t]['pnl_over_entry_equity']-left[t]['pnl_over_entry_equity'],
                'standard_fee_over_entry_equity':left[t]['fees_over_entry_equity'],
                'pressure_fee_over_entry_equity':right[t]['fees_over_entry_equity'],
                'standard_turnover_over_entry_equity':left[t]['gross_turnover_over_entry_equity'],
                'pressure_turnover_over_entry_equity':right[t]['gross_turnover_over_entry_equity']}
               for t in common]
    return {'common_closed_entries':len(common),'common_entries_and_exits':sum(left[t]['exit_at']==right[t]['exit_at'] for t in common),
        'standard_only_entries':sorted(set(left)-set(right)),'pressure_only_entries':sorted(set(right)-set(left)),
        'largest_normalized_deteriorations':sorted(records,key=lambda r:r['normalized_pnl_delta'])[:5],
        'largest_normalized_improvements':sorted(records,key=lambda r:-r['normalized_pnl_delta'])[:5],
        'all_common_cycles':records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,required=True)
    work = parser.parse_args().experiment.resolve()
    result = read(work/'others/results.json')
    protocol = read(work/'protocols/fee_pairs.json')
    assert result['status'] == 'COMPLETE'
    assert len(protocol['pairs']) == len(result['accounts']) == len(result['pressure_accounts']) == 7
    assert not (work/'others/fee_analysis.json').exists()
    output = {'status':'COMPLETE','new_account_runs':0,'pairs':{},
        'sources':{'results_sha256':digest(work/'others/results.json'),'protocol_sha256':digest(work/'protocols/fee_pairs.json'),
                   'analysis_sha256':digest(Path(__file__)),'ledger_sha256':digest(Path(__file__).with_name('fee_ledger.py'))},
        'normalization':'Closed-cycle fees and gross traded notional divided by the account equity recorded at the first actual fill time of that cycle; this is each account own capital path. Full MDD includes terminal open holdings.'}
    for item in protocol['pairs']:
        label = item['label']
        standard = result['accounts'][label]
        pressure = result['pressure_accounts'][label]
        assert standard['candidate_id'] == pressure['candidate_id'] == item['candidate_id']
        assert standard['definition'] == pressure['definition'] and standard['content_hash'] == pressure['content_hash']
        # Account-reference files are resolved by exact evidence equality, not naming convention.
        paths = {}
        for name,row in [('standard',standard),('pressure',pressure)]:
            matches = [p for p in (work/'others').glob('*.json') if read(p) == row['account_ref']]
            assert len(matches) == 1, (label,name,matches)
            paths[name] = matches[0].relative_to(work).as_posix()
        s = ledger(work,standard,{'account_path':paths['standard'],'fee_rate':.001})
        p = ledger(work,pressure,{'account_path':paths['pressure'],'fee_rate':.002})
        assert s['sessions'] == p['sessions']
        changes = {key:p['metrics'][key]-s['metrics'][key] for key in ('nar','drawdown','calmar','fees','closed_cycles')}
        changes['annual_return_deltas'] = {year:p['annual_returns'][year]-value for year,value in s['annual_returns'].items()}
        changes['actual_fill_count_delta'] = p['execution']['actual_fills']-s['execution']['actual_fills']
        changes['mean_cycle_fee_over_equity_delta'] = p['execution']['mean_closed_cycle_fees_over_entry_equity']-s['execution']['mean_closed_cycle_fees_over_entry_equity']
        for name,value in [('standard',s),('pressure',p)]:
            value['execution']['mean_closed_cycle_turnover_over_entry_equity'] = float(np.mean([x['gross_turnover_over_entry_equity'] for x in value['cycles']]))
        output['pairs'][label] = {'candidate_id':item['candidate_id'],'parameters':standard['parameters'],
            'standard':stripped(s),'pressure':stripped(p),'pressure_gates':pressure['pressure_gates'],
            'pressure_eligible':pressure['pressure_eligible'],'changes':changes,'matched_cycles':paired_cycles(s,p)}
        print('FEE_PAIR_ANALYZED',label,flush=True)
    # The three original configurations differ only in exit policy.
    original = [output['pairs'][cid]['parameters'] for cid in ('C0798','C0801','C0804')]
    assert all({k:v for k,v in q.items() if k != 'exit_policy'} == {k:v for k,v in original[0].items() if k != 'exit_policy'} for q in original)
    comparisons = []
    for control,new in [('C0798','C0966'),('C0801','C1010'),('C0804','C1045'),('C0804','C0909')]:
        base,other = output['pairs'][control],output['pairs'][new]
        comparisons.append({'control':control,'alternative':new,
            'standard_metric_delta':{key:other['standard']['metrics'][key]-base['standard']['metrics'][key] for key in ('nar','drawdown','calmar')},
            'pressure_metric_delta':{key:other['pressure']['metrics'][key]-base['pressure']['metrics'][key] for key in ('nar','drawdown','calmar')},
            'interpretation':'Complete configuration comparison; multiple parameter changes are not isolated exit-width effects.'})
    output['configuration_comparisons'] = comparisons
    output['pressure_pass_count'] = sum(x['pressure_eligible'] for x in output['pairs'].values())
    output['formal_all_candidate_stage_four_acceptance'] = False
    target = work/'others/fee_analysis.json'
    target.write_bytes((json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
    lines = ['# 少数代表的费用配对诊断','',
        '固定参数与完整账户合同，仅每侧费用从0.1%增至0.2%；标准证据复用，压力账户重新回放。2022—2026为已见开发池，2026年度数据截至10月30日。','',
        '|候选|标准NAR|压力NAR|标准Calmar|压力Calmar|标准MDD|压力MDD|原压力条件|',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for cid,v in output['pairs'].items():
        s,p = v['standard']['metrics'],v['pressure']['metrics']
        lines.append(f"|{cid}|{s['nar']:.4%}|{p['nar']:.4%}|{s['calmar']:.6f}|{p['calmar']:.6f}|{s['drawdown']:.4%}|{p['drawdown']:.4%}|{'通过' if v['pressure_eligible'] else '未通过'}|")
    lines += ['','## 实际调仓成本','',
        '费用归一化以每个周期首笔成交时已记录的账户权益为分母；两种费率分别使用各自资金路径。实际成交包含进出场及持有期间的调整。','',
        '|候选|标准/压力实际成交数|标准/压力平均周期费用占权益|标准/压力平均周期成交金额占权益|共同闭合入场/进出均同|',
        '|---|---:|---:|---:|---:|']
    for cid,v in output['pairs'].items():
        s,p = v['standard']['execution'],v['pressure']['execution']
        c = v['matched_cycles']
        lines.append(f"|{cid}|{s['actual_fills']}/{p['actual_fills']}|{s['mean_closed_cycle_fees_over_entry_equity']:.4%}/{p['mean_closed_cycle_fees_over_entry_equity']:.4%}|{s['mean_closed_cycle_turnover_over_entry_equity']:.4f}/{p['mean_closed_cycle_turnover_over_entry_equity']:.4f}|{c['common_closed_entries']}/{c['common_entries_and_exits']}|")
    lines += ['','原共同参数三族可用于解释退出机制差异；新领先点及C0909与原型存在多个参数差异，按完整配置解释。','',
        '完整年度、MDD段、末端持仓、最强反例和所有配对周期见[结构化分析](fee_analysis.json)。正式全候选稳健性、完整邻域及80%验收待阶段四授权。']
    (work/'others/fee_analysis.md').write_bytes(('\n'.join(lines)+'\n').encode())
    print('FEE_ANALYSIS_COMPLETE',output['pressure_pass_count'],'of',len(output['pairs']),flush=True)


if __name__ == '__main__':
    main()
