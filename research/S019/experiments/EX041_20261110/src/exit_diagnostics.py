"""Compact actual-fill comparisons for predeclared pure ATR +/-5% controls."""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
HELPER = WORK.parent/'EX040_20261110/src/prior_diagnostics.py'
HELPER_SHA = sha256(HELPER.read_bytes()).hexdigest()
PRE_FINALIZATION_SOURCE_SHA256 = '1575878dc7cdf309ab1e5f6dc10b43c4b7a73a8c882e118264efff05737ea59f'
SCRATCH = ROOT/'.tmp/s019-stage4-041/exit'
SCRATCH.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('s019_prior_exit_analysis', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
from czsc_trader import research_tools as d  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def load(reference):
    typed = d.EvidenceRef.from_dict(reference)
    raw = typed.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == reference['sha256']
    request = json.loads(raw)['request']
    definition = request['candidate_definition']
    params = json.loads(definition['parameters_json'])
    assert request['fee_rate'] == .001 and request['drawdown_basis'] == 'SESSION_CLOSE'
    cache = SCRATCH/(reference['sha256']+'.json')
    if cache.exists():
        record = read(cache)
        assert record['helper_sha256'] == HELPER_SHA and record['reference'] == reference and record['parameters'] == params
        value = record['value']
    else:
        ref_path = SCRATCH/(reference['sha256']+'_ref.json')
        save(ref_path,reference)
        value = helper.analyze(ref_path,params)
        save(cache,{'helper_sha256':HELPER_SHA,'reference':reference,'parameters':params,'value':value})
    assert value['reference'] == reference and len(value['sessions']) == 1212
    return value, {'reference':reference,'candidate_id':request['candidate_id'],
                   'content_sha256':request['content_sha256'],'strategy_source_sha256':definition['source_sha256'],
                   'parameters':params,'metrics':value['metrics'],'mdd_episode':value['mdd_episode'],
                   'exit_reason_counts':value['exit_reason_counts'],'yearly':value['yearly']}


def compact_cycle(cycle):
    keys = ['entry_at','exit_at','recorded_exit_at','exit_order_id','exit_reason','exit_facts',
            'net_pnl','net_return','entry_account_equity','pnl_over_entry_equity']
    return {k:cycle[k] for k in keys}


def compact_comparison(left,right):
    full = helper.compare(left,right)
    result = {k:v for k,v in full.items() if k not in ['changed_exits','left_only_entries','right_only_entries']}
    result['changed_exits'] = [{'entry_at':r['entry_at'],'perturbed':compact_cycle(r['left']),
                              'center':compact_cycle(r['right'])} for r in full['changed_exits']]
    result['perturbed_only_entries'] = [compact_cycle(c) for c in full['left_only_entries']]
    result['center_only_entries'] = [compact_cycle(c) for c in full['right_only_entries']]
    result['largest_cycle_contribution_deltas'] = result['largest_cycle_contribution_deltas'][:5]
    result['largest_daily_log_differences'] = result['largest_daily_log_differences'][:5]
    return result


def report(output):
    lines = ['# 纯ATR扰动的实际退出诊断','',
             f"状态：{output['status']}；固定范围C0367、C0355、C0264，已完成{len(output['centers'])}中心、{output['account_count']}份唯一账户，新增回放0。",'',
             '固定比较中心与其余参数完全一致的ATR下调5%（P002）、上调5%（P005）。复用既有公共账本，新增账户0；样本和标准费用保持原约定。真实入退场经cycle_id、fill、order、decision关联，股数及复利规模变化另按入场账户权益归一化。','',
             '| 中心/配置 | ATR | NAR | Calmar | MDD | 闭合周期 |','|---|---:|---:|---:|---:|---:|']
    for cid, result in output['centers'].items():
        for label, account in result['accounts'].items():
            m = account['metrics']
            lines.append(f"| {cid}/{label} | {account['parameters']['trail_atr']:.4f} | {m['nar']:.2%} | {m['calmar']:.3f} | {m['drawdown']:.2%} | {m['closed_cycles']} |")
    for cid,result in output['centers'].items():
        lines.extend(['',f'## {cid}',''])
        for label,comparison in result['comparisons'].items():
            account = result['accounts'][label]
            episode = account['mdd_episode']
            lines.append(f"**{label}**：{comparison['common_entries']}个共同入场中，{comparison['changed_exit_count']}个实际退出改变；扰动独有入场{len(comparison['perturbed_only_entries'])}个、中心独有入场{len(comparison['center_only_entries'])}个。前10个差异日占绝对日对数增长差的{comparison['top10_days_absolute_log_difference_share']:.2%}。MDD从{episode['peak']}至{episode['trough']}，恢复日为{episode['recovery'] or '截至样本末尚未恢复'}。")
            lines.append('')
            for row in comparison['largest_cycle_contribution_deltas'][:3]:
                lines.append(f"- {row['entry_at'][:10]}入场：扰动退出{row['left_exit']}，中心退出{row['right_exit']}；周期账本净盈亏/入场账户权益差{row['normalized_pnl_delta']*100:+.2f}个百分点。")
            lines.append('')
        center = result['accounts']['CENTER']
        ep = center['mdd_episode']
        lines.append(f"中心MDD段为{ep['peak']}至{ep['trough']}，恢复日为{ep['recovery'] or '截至样本末尚未恢复'}。逐项退出原因、跟踪线/价格/ATR等决策事实及关键差异日见JSON。")
    lines.extend(['','## 解释范围','',
                  'ATR倍数连续变化，实际退出是价格是否穿过跟踪线的离散决策；少量临界路径可以改变持有天数、后续入场和复利路径。按真实时点比较可把这些变化与持仓数量差异区分开。周期归一化损益用于描述给定账户路径的贡献；存在独有/重入周期时，同时保留两侧记录，整段比较优先使用可加的逐日对数增长差。',
                  '本诊断承接已观察到的邻域结果，属于已见开发样本的路径解释。正式参数通过率和费用压力仍由完整自检计算。源码、复用helper及账户引用/策略源码SHA均绑定于[结构化结果](exit_diagnostics.json)。'])
    (WORK/'others/exit_diagnostics.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--centers',nargs='+',default=['C0367'])
    args = parser.parse_args()
    started = perf_counter()
    path = WORK/'others/exit_diagnostics.json'
    code_sha = sha256(Path(__file__).read_bytes()).hexdigest()
    output = read(path) if path.exists() else {
        'schema':'S019-EX041-actual-exit-diagnostics-v1','centers':{},'new_strategy_accounts':0,
        'plan':{'labels':['CENTER','P002','P005'],'comparison':'Pure ATR -5%/+5%; all other effective parameters equal.',
                'alignment':'Actual fills -> order -> decision; exact common entry times; preserve unmatched cycles.',
                'contribution':'Ledger net PnL / entry account equity; additive daily log differences for full path.'},
        'runs':[]}
    if output.get('source_sha256'):
        assert output['helper_sha256']==HELPER_SHA
        if output['source_sha256']!=code_sha:
            assert output['source_sha256']==PRE_FINALIZATION_SOURCE_SHA256
            output.setdefault('source_revisions',[]).append({
                'previous_sha256':output['source_sha256'],'current_sha256':code_sha,
                'change':'Explicit finalization metadata: COMPLETE only when all three fixed centers are present; account count and report status added. Analysis and cached numerical results unchanged.'})
    effective = read(WORK/'others/center_accounts.json')
    for cid in args.centers:
        center, compact = load(effective[cid])
        accounts = {'CENTER':compact}
        comparisons = {}
        for label,multiplier in [('P002',.95),('P005',1.05)]:
            ref = read(WORK/f'others/{cid}_{label}_account.json')
            value, account = load(ref)
            p,q = compact['parameters'],account['parameters']
            assert {k:v for k,v in p.items() if k!='trail_atr'}=={k:v for k,v in q.items() if k!='trail_atr'}
            assert abs(q['trail_atr']-p['trail_atr']*multiplier)<1e-12
            assert compact['strategy_source_sha256']==account['strategy_source_sha256']
            accounts[label]=account
            comparisons[label]=compact_comparison(value,center)
        output['centers'][cid]={'accounts':accounts,'comparisons':comparisons}
        print('EXIT_DIAGNOSTICS',cid,flush=True)
    complete = set(output['centers']) == {'C0367','C0355','C0264'}
    account_count = len({a['reference']['sha256'] for c in output['centers'].values() for a in c['accounts'].values()})
    assert not complete or account_count == 9
    output.update(status='COMPLETE' if complete else 'COMPLETE_FOR_LISTED_CENTERS',account_count=account_count,
                  planned_centers=['C0367','C0355','C0264'],source_sha256=code_sha,helper_sha256=HELPER_SHA,
                  helper_path=str(HELPER.relative_to(ROOT)),public_reader_sha256=sha256((WORK.parent/'EX013_20261110/src/runner.py').read_bytes()).hexdigest())
    output['runs'].append({'centers':args.centers,'elapsed_seconds':perf_counter()-started,'new_strategy_accounts':0})
    save(path,output)
    report(output)


if __name__=='__main__':
    main()
