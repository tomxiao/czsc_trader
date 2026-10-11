"""EX072 readonly first-touch audit, corrected raw labels and fixed-centre refutation."""
import json,shutil
from pathlib import Path
import driver as d
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

def main():
    exp,plan,path=d.stage();common=d.oldcommon();ctx=common.context(1)
    source=path/'src/postprocess.py';assert d.digest(source)==d.digest(__file__)
    completion=d.read(d.WORK/'execution_complete.json');assert d.digest(d.WORK/'centre.pkl.gz')==completion['cache_sha256']
    pair=common.cache_read(d.WORK/'centre.pkl.gz');assert serialize_evaluation_evidence(*pair)==d.read(d.public(completion['reference']))
    refs=d.read(path/'protocols/result_references.json');old=d.read(d.public(refs['verification']))
    assert old==d.read(d.WORK/'verification.json') and old['status']=='PASS' and old['whole_formal_native_exact'] is True
    proof=d.read(path/'protocols/orders_technical_amendment_references.json');assert d.digest(path/'src/execution_links.py')==proof['new_source']['sha256']
    checker=d.load('overnight_order_links_new_native',path/'src/execution_links.py');orders=checker.verify(*pair)
    run=pair[1].runs[0].execution;trades=run.trades;closed=int(trades.status.eq('CLOSED').sum());opened=int(trades.status.eq('OPEN').sum())
    assert closed==old['economics']['closed_trades']==107 and closed+opened==len(trades)==108
    refused=set(run.decisions.loc[run.decisions.pressure_gate_rejected,'decision_id'])
    assert not run.orders.loc[run.orders.side.eq('BUY')].decision_id.isin(refused).any()
    assert not run.fills.loc[run.fills.side.eq('BUY')].decision_id.isin(refused).any()
    assert old['economics']['gates']=={'return':True,'annual_drawdown':True,'frequency':False,'negative_buyhold_year_profit':True}
    assert not (d.WORK/'parameters').exists()
    corrected=old['raw_counts'].copy();incorrect_label=corrected.pop('closed_trades')
    assert incorrect_label==len(trades)
    corrected|={'raw_trade_rows':len(trades),'closed_cycles':closed,'open_cycles':opened}
    report={'status':'COMPLETE_FIXED_CENTRE_REFUTATION','native_whole_source_cash_state_audit':'PASS','orders_first_touch_audit':orders,
       'native_reference':completion['reference'],'independent_verification_reference':refs['verification'],'prospective_method_reference':d.read(path/'protocols/plan_reference.json'),
       'prospective_integer_budget36_reference':d.read(path/'protocols/prospective_supplement_reference.json'),'preflight_reference':refs['preflight'],
       'technical_amendment':proof,'baseline_readonly_orders_reference':d.read(path/'protocols/baseline_order_audit_reference.json'),
       'raw_count_label_correction':{'old_public_field':'raw_counts.closed_trades','old_value':incorrect_label,'meaning':'len(native.trades) includes one OPEN cycle; raw row count not closed trade count. Original independent economic closed107 was correct. Preserve old immutable verification and explicitly publish corrected labels.','corrected':corrected},
       'economics':old['economics'],'baseline_economics':old['baseline']['economics'],'annual_comparison':{y:{'new_return':a['return'],'new_annual_dd':a['drawdown'],'baseline_return':old['baseline']['economics']['annual'][y]['return'],'baseline_annual_dd':old['baseline']['economics']['annual'][y]['drawdown']} for y,a in old['economics']['annual'].items()},
       'centre_comparison':{'cagr_difference':old['economics']['net_cagr']-old['baseline']['economics']['net_cagr'],'full_dd_difference':old['economics']['full_drawdown']-old['baseline']['economics']['full_drawdown'],'closed_cycle_difference':closed-old['baseline']['economics']['closed_trades']},
       'raw_counts':corrected,'stop_confirmed':True,'stop_reason':'Original frequency gate failed:107 closed/1636*60=3.924205378973105 <4; all other original3 gates PASS. No32/no fee/no3/5/no optimization.',
       'latest_fivechecks_availability':{'definition':'S013-EX062-five-independent-checks-v1','full_panel':'NOT_RUN_CENTRE_ORIGINAL4_FAILED','parameter_Q10_Q90':'NOT_RUN_NO_STANDARD32','fee':'NOT_RUN_NO_STRESS_ACCOUNT','time_uncertainty':'NOT_COMPUTED_IN_THIS_CENTRE_ONLY_REFUTATION','centre_profit_concentration':old['economics']['profit_concentration'],'PBO_DSR':'NOT_AVAILABLE_NO_FULL_FAMILY_RETURN_MATRIX'},
       'counts':{'new_financial_accounts':1,'baseline_financial_reuse':1,'new_standard32':0,'new_fee':0,'new_neighbours':0,'new_technical_financial':0,'registration':0,'delivery_assembly':0},
       'claims':'Fixed expression failed one original hardgate and whole-account improvement:2023 improves but centre CAGR decreases and fullDD increases. Actual rejection31 is ownpath signal count, not15 static oldentry or hypothetical lost/winning trade attribution. No removed group future-profit threshold selection. Overall robust target not achieved; root scientific review pending.',
       'provider_calls':common.SOURCE_CALLS}
    assert not common.SOURCE_CALLS
    d.write(d.WORK/'centre_refutation.json',report)
    outref=d.put(ctx,exp,d.WORK/'centre_refutation.json','overnight-filter-centre-failed-frequency-complete-refutation')
    d.write(path/'protocols/centre_refutation_reference.json',outref)
    lines=['# 隔夜下跌压力买入过滤：固定中心反证','',
      '在原C8880自身空仓、熊市原入场资格和原确认均通过时，如果此前4个完整交易日的隔夜下跌幅度总和大于日内下跌幅度总和，就放弃当日买入；保持原退出规则和退出记忆。',
      '', '固定中心未满足原四门：交易频率未过，其他三门通过。少买确实改善2023年，但整体收益下降、全期回撤变大，因此这条固定表达没有实现研究要求。',
      '', '|指标|原C8880|过滤后C9072|','|---|---:|---:|']
    for label,key in (('净年化收益','net_cagr'),('全期最大回撤','full_drawdown'),('每60日闭合交易','frequency60'),('闭合交易数','closed_trades')):
        lines.append(f"|{label}|{old['baseline']['economics'][key]}|{old['economics'][key]}|")
    lines+=['','|自然年|原收益|新收益|原年度回撤|新年度回撤|','|---|---:|---:|---:|---:|']
    for y,a in report['annual_comparison'].items():lines.append(f"|{y}|{a['baseline_return']:.4%}|{a['new_return']:.4%}|{a['baseline_annual_dd']:.4%}|{a['new_annual_dd']:.4%}|")
    lines+=['',f'原116笔闭合交易减少到107笔，低于频率硬门；实际108笔买入、107笔卖出，107个闭合周期和1个仍持有周期。自身新路径31次拒绝，不能将其当作静态15个旧机会或31笔减少的实际交易。',
      '', '已按事前规则停止，没有执行32点、双倍费用、3/5邻域、参数优化或候选登记。完整五项自检因此没有执行，不能把缺失结果写成通过或零值。',
      '', '禁用过滤的1636个历史信号每个原字段与原源及旧原生结果精确相同；启用后的压力公式、策略自身状态与退出记忆、完整现金账本和原生身份已独立核验，订单成交通过因果日期、手数、费用、开盘价/日内首触核验。',
      '', '原公开verification的raw_counts.closed_trades字段误标为108，实际它是含1个OPEN周期的交易行总数；经济闭合数始终正确107。原证据保留，本报告显式更正字段标签。一次只读订单审计pandas.dt列访问技术失败及对应旧源、新源和具体traceback已公开，未复跑财务账户。',
      '', '这些都是已见开发池结果，不是新封存验证；删除买入会改变后续状态和资金路径，因此不能仅凭被拒绝机会的事后收益解释机制效果。总体稳健目标尚未实现，科学评审由root完成。','']
    (d.WORK/'centre_refutation.md').write_text('\n'.join(lines),encoding='utf-8')
    d.write(path/'protocols/centre_refutation_report_reference.json',d.put(ctx,exp,d.WORK/'centre_refutation.md','overnight-filter-readable-centre-refutation'))
    print(json.dumps({'status':report['status'],'reference':outref,'counts':report['counts'],'raw_counts':corrected,'four_gates':old['economics']['gates']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
