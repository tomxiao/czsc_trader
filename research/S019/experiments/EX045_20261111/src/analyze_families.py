"""Analyze completed four-family adaptation using metadata and selected public ledgers only."""
from collections import Counter
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
WORK = ROOT / 'research/S019/experiments/EX045_20261111'
OUT = WORK / 'others'
CACHE = ROOT / '.tmp/s019-ex045-family-comparison'
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
os.environ['MPLCONFIGDIR'] = str(CACHE/'matplotlib')
sys.dont_write_bytecode = True
EX044 = ROOT / 'research/S019/experiments/EX044_20261110/src/compare_participation.py'
EXPECTED_EX044 = '9b7b633dabe52c188726fdd5b54a943a73fa3f977c4cc74e946459f4df55267f'
assert sha256(EX044.read_bytes()).hexdigest() == EXPECTED_EX044
spec = importlib.util.spec_from_file_location('ex044_readonly_helper',EX044)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
import numpy as np  # noqa: E402
from czsc_trader.research_tools import EvidenceRef  # noqa: E402

module.WORK, module.SCRATCH = WORK, CACHE
module.helper.WORK, module.helper.SCRATCH = WORK, CACHE / 'helper'
module.helper.SCRATCH.mkdir(parents=True,exist_ok=True)
read, save, digest = module.read, module.save, module.digest
GATES = ('nar','calmar','absolute_dd','relative_dd','frequency_median','frequency_coverage')


def select(rows):
    eligible = [r for r in rows if all(r['candidate']['gates'].values())]
    if eligible:
        chosen = sorted(eligible,key=lambda r:(-r['candidate']['nar'],r['trial_number']))[0]
        return {'status':'SIX_GATE_REPRESENTATIVE','key':chosen['name'],'candidate_id':chosen['id'],
                'rule':'Original six gates, then maximum unrounded NAR; trial number resolves exact NAR ties.'}
    remaining = [r for r in rows if all(r['candidate']['gates'][k] for k in GATES if k!='calmar')]
    if remaining:
        chosen = sorted(remaining,key=lambda r:(-r['candidate']['calmar'],-r['candidate']['nar'],r['trial_number']))[0]
        return {'status':'CALMAR_GAP_DIAGNOSTIC','key':chosen['name'],'candidate_id':chosen['id'],
                'rule':'Other five gates pass; maximum unrounded Calmar, then NAR; diagnostic anchor only.'}
    return {'status':'ROOT_SELECTION_REQUIRED','key':None,'candidate_id':None,
            'rule':'No observation passes the other five gates; no automated relaxation or replacement.'}


def distribution(values):
    return {k:float(v) for k,v in zip(('min','q25','median','q75','max'),np.quantile(values,[0,.25,.5,.75,1]),strict=True)}


def boundary(row, space):
    result = {}
    for name,b in space.items():
        value = row['parameters'][name]
        position = (value-b['low'])/(b['high']-b['low'])
        assert -1e-12 <= position <= 1+1e-12
        result[name] = {'value':value,'relative_position':position,
                        'exact_lower':bool(np.isclose(value,b['low'],atol=1e-12,rtol=0)),
                        'exact_upper':bool(np.isclose(value,b['high'],atol=1e-12,rtol=0)),
                        'near_lower_5pct':position<=.05,'near_upper_5pct':position>=.95}
    return result


def plot_tradeoff(summary, families, controls, source):
    if importlib.util.find_spec('matplotlib') is None:
        return {'status':'NOT_AVAILABLE','reason':'Matplotlib is not installed; no dependency added.'}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    colors = {'hard_hard':'#0072B2','hard_linear':'#009E73','ramp_linear':'#D55E00','daily_close_hard':'#CC79A7'}
    figure, axis = plt.subplots(figsize=(10.5,6.5),layout='constrained')
    offsets = [(9,12),(9,-20),(9,20),(-70,-22)]
    for index,(name,family) in enumerate(families.items()):
        rows = [r for r in summary.values() if r['family']==name]
        axis.scatter([r['candidate']['drawdown']*100 for r in rows],
                     [r['candidate']['nar']*100 for r in rows],s=35,color=colors[name],alpha=.7,label=name,zorder=3)
        control = summary[controls[name]]['candidate']
        axis.scatter(control['drawdown']*100,control['nar']*100,s=85,marker='D',
                     facecolors='none',edgecolors=colors[name],linewidths=1.7,zorder=4)
        selected = family['selected']
        if selected['key']:
            row = summary[selected['key']]
            m = row['candidate']
            xy = (m['drawdown']*100,m['nar']*100)
            axis.scatter(*xy,s=190,marker='*',c=colors[name],edgecolors='black',linewidths=.7,zorder=5)
            suffix = ' (gap)' if selected['status']=='CALMAR_GAP_DIAGNOSTIC' else ''
            axis.annotate(row['id']+suffix,xy,xytext=offsets[index],textcoords='offset points',fontsize=9,
                          arrowprops={'arrowstyle':'-','color':colors[name],'lw':.7},zorder=6)
    all_mdd = [r['candidate']['drawdown']*100 for r in summary.values()]
    all_nar = [r['candidate']['nar']*100 for r in summary.values()]
    xlim = (max(0,min(all_mdd)-1.5),max(all_mdd)+1.5)
    ylim = (min(min(all_nar),55)-5,max(max(all_nar),55)+8)
    axis.axhline(55,color='#333333',linestyle='--',linewidth=1,label='NAR = 55%')
    axis.plot(xlim,[5*x for x in xlim],color='#666666',linestyle=':',linewidth=1.3,label='Calmar = 5')
    axis.set(xlim=xlim,ylim=ylim,xlabel='Maximum drawdown, session close (%)',ylabel='Net annualized return (%)',
             title='S019 EX045: all 96 proposals across four strategy families')
    axis.grid(alpha=.18)
    handles,labels = axis.get_legend_handles_labels()
    handles.extend([Line2D([],[],marker='D',linestyle='None',markerfacecolor='none',color='black',markersize=6),
                    Line2D([],[],marker='*',linestyle='None',color='black',markersize=10)])
    labels.extend(['Prespecified control','Selected representative / labeled gap diagnostic'])
    axis.legend(handles,labels,fontsize=8,loc='upper left',bbox_to_anchor=(1.02,1),borderaxespad=0,framealpha=.94)
    figure.text(.01,.005,'Observed development sample through 2026-10-30. Each family: 24 proposals; active dimensions: 4 / 5 / 6 / 4.',fontsize=8,color='#555555')
    path = OUT/'family_tradeoff.png'
    figure.savefig(path,dpi=160,metadata={'Source':source['analysis_sha256'],'Description':'All 96 proposals; no additional selection score.'})
    plt.close(figure)
    return {'status':'COMPLETE','path':'others/family_tradeoff.png','sha256':digest(path),'points':96}


def main():
    begun = perf_counter()
    execution_path = WORK / 'others/execution.json'
    if not execution_path.exists() or read(execution_path)['status'] != 'COMPLETE':
        raise SystemExit('NOT_READY: EX045 execution must be COMPLETE before any account reads')
    config = read(WORK/'protocols/search.json')
    summary = read(WORK/'others/summary.json')
    specs = read(WORK/'others/candidate_specs.json')['specs']
    assert len(specs)==len(summary)==96 and config['trial_budget']==24 and len(config['families'])==4
    assert {s['name'] for s in specs} == set(summary)
    source = {'analysis_sha256':digest(Path(__file__)), 'ex044_helper_sha256':EXPECTED_EX044,
              'ex043_helper_sha256':module.EXPECTED_HELPER,
              'public_reader_sha256':digest(ROOT/'research/S019/experiments/EX013_20261110/src/runner.py'),
              'strategy_file_sha256':digest(WORK/'src/strategy.py'),
              'search_sha256':digest(WORK/'protocols/search.json'),
              'run_manifest_sha256':digest(WORK/'protocols/run_manifest.json'),
              'summary_sha256':digest(WORK/'others/summary.json'),
              'execution_sha256':digest(execution_path)}
    files, headers = {}, {}
    for s in specs:
        key = s['name']
        row = summary[key]
        result_path = WORK/f'others/trials/{key}_result.json'
        assert read(result_path)==row
        assert row['id']==s['candidate_id'] and row['parameters']==s['parameters'] and row['content_hash']==s['content_hash']
        assert set(row['candidate']['gates'])==set(GATES)
        assert row['candidate']['eligible']==all(row['candidate']['gates'].values())
        assert json.loads(row['definition']['parameters_json'])==row['parameters']
        ref = EvidenceRef.from_dict(row['account'])
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest()==ref.sha256
        h = json.loads(raw)
        assert h['request_hash']==row['request_sha256']
        assert h['request']['content_sha256']==row['content_hash'] and h['request']['candidate_definition']==row['definition']
        assert h['request']['fee_rate']==.001 and h['request']['measurement_tier']=='FORMAL'
        headers[key] = {'benchmark_identity':h['benchmark_identity'],'input_ref':h['input_ref']}
        files[key] = {'result_sha256':digest(result_path),'account_ref':row['account'],'request_sha256':row['request_sha256']}
    assert len({json.dumps(v,sort_keys=True) for v in headers.values()})==1
    families, selections, compact_trials = {}, {}, []
    controls = {}
    for family in config['families']:
        name,space = family['name'],family['space']
        rows = sorted([r for r in summary.values() if r['family']==name],key=lambda r:r['trial_number'])
        assert len(rows)==24 and [r['trial_number'] for r in rows]==list(range(24))
        controls[name] = rows[0]['name']
        assert rows[0]['parameters']==family['control_parameters']
        selection = select(rows)
        selections[name] = selection
        failure_patterns = Counter()
        for row in rows:
            failed = [k for k in GATES if not row['candidate']['gates'][k]]
            failure_patterns['+'.join(failed) or 'ALL_PASS']+=1
            compact_trials.append({'family':name,'key':row['name'],'trial_number':row['trial_number'],
                                   'candidate_id':row['id'],'proposed_candidate_id':row['proposed_candidate_id'],
                                   'parameters':row['parameters'],'metrics':row['candidate'],'failed_gates':failed,
                                   'boundaries':boundary(row,space),'provenance':row['provenance'],
                                   'content_hash':row['content_hash'],'account_ref':row['account']})
        families[name] = {'proposal_count':24,'unique_accounts':len({r['account']['sha256'] for r in rows}),
                          'active_continuous_dimensions':len(space),
                          'active_parameter_names':list(space),
                          'illustrative_full_three_level_neighbor_count':3**len(space)-1,
                          'alias_count':sum(r['provenance']['kind']=='EXACT_ALIAS' for r in rows),
                          'six_gate_pass_count':sum(r['candidate']['eligible'] for r in rows),
                          'eligible_candidates':[r['id'] for r in rows if r['candidate']['eligible']],
                          'gate_failure_counts':{k:sum(not r['candidate']['gates'][k] for r in rows) for k in GATES},
                          'failure_patterns':dict(failure_patterns),
                          'distributions':{k:distribution([r['candidate'][k] for r in rows])
                                           for k in ('nar','drawdown','calmar','fees','closed_cycles','frequency_median','frequency_coverage')},
                          'parameter_distributions':{k:distribution([r['parameters'][k] for r in rows]) for k in space},
                          'boundary_counts':{k:{b:sum(boundary(r,space)[k][b] for r in rows)
                                                  for b in ('exact_lower','exact_upper','near_lower_5pct','near_upper_5pct')} for k in space},
                          'selected':selection}
    needed = sorted(set(controls.values())|{s['key'] for s in selections.values() if s['key'] is not None})
    accounts, exposures, modes, normalized = {}, {}, {}, {}
    for key in needed:
        row = summary[key]
        normalized[key] = {**row,'candidate_id':row['id'],'account_ref':row['account'],'label':'trials/'+key}
        accounts[key], exposures[key], modes[key] = module.read_with_exposure(normalized[key],source)
        print('READ',key,modes[key],flush=True)
    pairs = []
    requests = [(s['key'],controls[name],'ADAPTED_VS_OWN_CONTROL') for name,s in selections.items() if s['key'] is not None]
    for left,right in [('hard_linear','hard_hard'),('ramp_linear','hard_linear'),('daily_close_hard','hard_hard')]:
        if selections[left]['key'] and selections[right]['key']:
            requests.append((selections[left]['key'],selections[right]['key'],'ADAPTED_FAMILY_COMPARISON'))
    for left,right,kind in requests:
        comparison = module.paired(left,right,exposures,accounts)
        comparison['comparison_kind'] = kind
        comparison['parameter_differences'] = {k:{'other':summary[left]['parameters'][k],'baseline':summary[right]['parameters'][k]}
                                               for k in summary[left]['parameters'] if summary[left]['parameters'][k]!=summary[right]['parameters'][k]}
        pairs.append(comparison)
    ledger_summaries = {}
    for key in needed:
        a = accounts[key]
        peak, trough = a['mdd_episode']['peak'], a['mdd_episode']['trough']
        peak_day = a['sessions'][0] if peak=='INITIAL_CASH' else peak
        loss_days = sorted([{'session':day,'return':ret} for day,ret in zip(a['sessions'],a['daily_returns'],strict=True)
                            if peak_day < day <= trough and ret < 0],key=lambda d:d['return'])[:5]
        ledger_summaries[key] = {**{k:v for k,v in a.items() if k not in ('cycles','sessions','daily_returns')},
                                  'candidate_id':summary[key]['id'],'parameters':summary[key]['parameters'],
                                  'content_hash':summary[key]['content_hash'],
                                  'largest_cycle_losses_by_entry_equity':sorted(a['cycles'],key=lambda c:c['pnl_over_entry_equity'])[:5],
                                  'largest_cycle_losses_by_trade_return':sorted(a['cycles'],key=lambda c:c['net_return'])[:5],
                                  'mdd_largest_loss_days':loss_days,
                                  'mdd_overlapping_closed_cycles':[c for c in a['cycles'] if c['entry_at'][:10]<=trough and c['exit_at'][:10]>=peak_day],
                                  'previously_seen_november_cycle':[c for c in a['cycles'] if c['entry_at'].startswith('2025-11-19')]}
    out = {'status':'COMPLETE','proposal_count':96,'new_accounts':0,'sources':source,
           'input_bindings':files,'families':families,'all_trials':compact_trials,
           'selected_ledgers':ledger_summaries,'comparisons':pairs,'read_modes':modes,
           'r4_second_anchor':selections['ramp_linear'],'elapsed_seconds':perf_counter()-begun,
           'r4_third_anchor':selections['hard_linear'] if selections['hard_linear']['status']=='SIX_GATE_REPRESENTATIVE'
           else {'status':'NOT_AVAILABLE_NO_SIX_GATE_HARD_LINEAR','key':None,'candidate_id':None},
           'method':['All 96 proposal metrics are experiment result metadata bound to public account headers; selected ledgers are fully materialized and metrics rechecked.',
                     'All-family trading counts refer to closed cycles. Actual fill counts are separately reported for every selected/control ledger.',
                     'Four families receive 24 proposals each, including controls, with 4/5/6/4 search dimensions; this is finite adaptation evidence.',
                     'If future formal self-check uses the full per-axis minus5%/center/plus5% Cartesian neighborhood, illustrative neighbor counts are 80/242/728/80; legal filtering and exact deduplication determine actual points.',
                     'Searched participation and exit widths remain active axes in later self-check. Future cost is a limitation, with no dimension penalty or change to original six-gate/NAR selection.',
                     'Representatives pass original six gates then maximize NAR; failed families use the explicitly declared other-five-gates/maximum-Calmar diagnostic rule.',
                     'Boundary proximity means within 5% of the declared continuous domain and was fixed before reading complete results.',
                     'Cross-family representatives may differ in several parameters. Parameter differences accompany every pair.',
                     'Adapted representative differences describe improvements/costs of complete configurations. Structural attribution uses matched EX043/EX044 and future R4 comparisons.',
                     'Family-specific independent seeds and different search dimensions affect coverage. Zero eligible observations means none found within this 24-proposal budget.',
                     'Full-period and annual log differences and harmed cycles accompany the previously seen November example.',
                     'No fANOVA/model fitting, no new accounts, and no formal robustness qualification.']}
    OUT.mkdir(parents=True,exist_ok=True)
    out['tradeoff_plot'] = plot_tradeoff(summary,families,controls,source)
    save(OUT/'family_comparison.json',out)
    lines = ['# EX045 四家族有限适配对照','', '96 个提议全部保留；代表和各族控制按公共账户读取。新增账户 0。','',
             '|家族|六门达标/24|代表|选择状态|NAR|MDD|Calmar|','|---|---:|---|---|---:|---:|---:|']
    for name,f in families.items():
        s = f['selected']
        if s['key']:
            m = summary[s['key']]['candidate']
            lines.append(f"|{name}|{f['six_gate_pass_count']}|{s['candidate_id']}|{s['status']}|{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.5f}|")
        else:
            lines.append(f"|{name}|0|待主线程选择|{s['status']}|—|—|—|")
    lines.extend(['','各族完整分布、六门失败组合、边界位置和费用/闭合周期数见 JSON；代表账户另含实际成交数、年度收益、MDD 起止、最大亏损周期及成对仓位差。',
                  '每族首个控制计入 24 提议；四族连续参数维度分别为 4/5/6/4。家族代表比较同时披露参数差，属于本轮有限适配结果。',
                  '代表相对控制及跨族代表差异按完整配置的改善与代价解释；结构作用结合 EX043/EX044 及后续 R4 同参数配对。各族独立种子、参数维度和覆盖难度已披露，某族零达标记为本轮 24 次提议内未发现达标配置。',
                  '若后续阶段四仍对每个有效轴采用 −5%/中心/+5% 全笛卡尔邻域，四族名义邻点数分别为 80/242/728/80，实际点集按合法性与精确去重确定。已搜索的参与宽度、退出宽度继续作为有效轴；后续成本仅用于说明研究投入，原六门与 NAR 选择保持。',
                  'R4 第二锚点采用 ramp_linear 的原六门代表；该族无全门点时采用其余五门合格集合内最高 Calmar 的缺口诊断点；集合为空交回主线程。','',
                  'R4 可加入 hard_linear 原六门合格中最高 NAR 为第三锚点，用同参数三种退出×三档 ATR 检查达标配置的机制取舍，最终点集在 R4 冻结前确定。','',
                  f"分析源码 SHA256：`{source['analysis_sha256']}`",'', '完整输出：`others/family_comparison.json`。'])
    if out['tradeoff_plot']['status']=='COMPLETE':
        lines.extend(['','![四族全部 96 个提议的 NAR 与 MDD 分布](family_tradeoff.png)'])
    (OUT/'family_comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'status':'COMPLETE','selected_accounts':len(needed),'seconds':out['elapsed_seconds'],'r4':out['r4_second_anchor']}))


if __name__=='__main__':
    main()
