"""Save a bounded review artifact; never allocate an experiment or evaluate accounts."""
from collections import Counter
from pathlib import Path
import json
import math
import s013_existing_candidate_review as base


def main():
    summary=base.read(base.OUT/'summary.json')
    centres=base.read(base.OUT/'centres.json')
    params=base.read(base.OUT/'standard32.json')
    diagnostics=base.read(base.OUT/'latest_five_diagnostics.json')
    assert summary['registered_candidates']==203 and summary['current_candidate_count']==8
    assert len(params['rows'])==len(diagnostics['rows'])==8
    detailed=[]
    for row in summary['rows']:
        cid=row['candidate_id']
        c=next(r for r in centres['rows'] if r['candidate_id']==cid)
        p=next(r for r in params['rows'] if r['candidate_id']==cid)
        f=next(r for r in diagnostics['rows'] if r['candidate_id']==cid)
        ev=base.read(base.ROOT/c['source'])
        assert base.digest(base.ROOT/c['source'])==c['source_sha256']
        a=ev['assessment_evidence'][0]
        session_counts=Counter(x['session'][:4] for x in a['account'])
        cycle_counts=Counter(x['exit_session'][:4] for x in a['closed_cycles'])
        years=c['positive_buyhold_years']
        days=sum(session_counts[y] for y in years)
        closed=sum(cycle_counts[y] for y in years)
        assert days==row['positive_year_days'] and closed==row['positive_year_closed_trades']
        assert row['positive_year_minimum_closed_trades']==math.ceil(days/15)
        assert not row['all_review_conditions_pass'] and p['available_points']==32 and p['joint_pass']<32
        metrics={d['metric']:d for d in f['panel_row']['diagnostics']}
        compact_points=[]
        for point in p['points']:
            base.ref_path(point['reference'])
            e=point['economics']
            compact_points.append({'index':point['point_index'],'candidate_id':point['candidate_id'],
                'reference':point['reference'],'result_hash':point['result_hash'],
                'gates':e['gates'],'joint_pass':e['qualified'],
                'cagr':e['net_cagr'],'drawdown':e['full_drawdown'],
                'closed_trades':e['closed_trades']})
        detailed.append({**row,'centre_source':c['source'],'centre_source_sha256':c['source_sha256'],
            'content_sha256':c['content_sha256'],'centre_net_cagr':c['economics']['net_cagr'],
            'centre_drawdown':c['economics']['full_drawdown'],'centre_frequency60':c['economics']['frequency60'],
            'centre_gates':c['economics']['gates'],'annual':c['economics']['annual'],
            'benchmark_annual':c['economics']['benchmark_annual'],
            'standard32_plan':p['plan_reference'],'standard32_gate_counts':p['point_gate_counts'],
            'standard32_dimensions':p['dimensions'],'standard32_sources':compact_points,
            'five_checks':{'parameter_absolute_q10_cagr':f['absolute_q10_cagr'],
               'parameter_absolute_q90_drawdown':f['absolute_q90_drawdown'],
               'rolling_excess_q10':metrics['ROLLING_EXCESS_Q10'],
               'profit_concentration':metrics['PROFIT_CONCENTRATION'],
               'stress_annual_loss':metrics['STRESS_ANNUAL_LOSS'],
               'stress_source':f['stress_reference'],'stress_economics':f['stress_economics'],
               'uncertainty':f['panel_row']['uncertainty'],
               'protocol':f['protocol'],'coverage_gaps':f['panel_row']['coverage_gaps'],
               'family_selection_bias':'INSUFFICIENT_DATA_FULL_FAMILY_RETURN_MATRIX_NOT_SUPPLIED'}})
    destination=base.ROOT/'research/S013/reviews/20261012_existing_candidates'
    destination.mkdir(parents=True,exist_ok=True)
    review={'kind':'EXISTING_CANDIDATE_READ_ONLY_ACCOUNT_REVIEW','review_date':'2026-10-12','timezone':'Asia/Shanghai',
      'scope':'S013 registered candidates only; 510500.SH existing authorised development pool; no other family data',
      'human_confirmed_review_conditions':{
        'robustness':'中心四项硬门达标，且标准32点全部仍通过四门',
        'positive_buyhold_year_frequency':'所有buyhold盈利年份合并计算达标',
        'frequency_threshold':4,'frequency_window_sessions':60,
        'cycle_year_assignment':'实际退出日期；跨年交易归退出年；未闭合持仓不计',
        'year_classification':'使用已有真实连续buyhold年度净收益；只作事后审查，不供策略预知',
        'original_four_gates_retained':True,'positive_year_frequency_is_additional_review_condition':True},
      'registered_candidate_count':203,'historical_incomparable':summary['historical_incomparable'],
      'current_comparable_centres':8,'current_comparable_standard_points':256,
      'positive_buyhold_years':summary['positive_years'],'positive_year_sessions':1152,
      'minimum_positive_year_closed_trades':77,'qualified_candidates':[],
      'rows':detailed,'registered_inventory':[{k:r[k] for k in ('candidate_id','content_sha256','source','source_sha256','schema_version','status')} for r in centres['rows']],
      'verification':{'registered_sources_authenticated':203,'current_evidence_sha_and_public_semantic_validation':'PASS',
        'actual_fill_cash_mark_and_closed_cycle_reconciliation':'PASS','parameter_plan_and_point_bindings':'PASS',
        'independent_exit_date_frequency_count':'PASS_8_OF_8',
        'latest_diagnostic_helper_source_sha256':diagnostics['helper_source_sha256'],
        'legacy_benchmark_accounts_replayed_or_rewritten':False},
      'limits':{'new_experiments':0,'new_accounts':0,'new_parameter_designs':0,'new_fits':0,
        'new_market_data':0,'old_candidate_eligibility_changed':False,'research_remains_paused':True,
        'five_diagnostic_scope':'latest definitions, fixed existing baseline and32 accounts; independent fee evidence for3;5 fee gaps explicit; missing family correction explicit',
        'historical_gap':'195 registered candidates retain schema5 NextOpenBuyHold evidence, not reassessed as current fixed1percent benchmark',
        'interpretation':'No candidate confirmed eligible under this review; not proof no such strategy can exist or that all historical candidates economically fail'}}
    sources=('s013_existing_candidate_review.py','s013_existing_parameter_review.py','s013_existing_fivecheck_review.py','s013_existing_review_closeout.py')
    review['review_source_sha256']={name:base.digest(base.ROOT/'.tmp'/name) for name in sources}
    with (destination/'review.json').open('x',encoding='utf-8') as stream:
        json.dump(review,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    for name in sources:
        with (destination/name).open('xb') as stream:
            stream.write((base.ROOT/'.tmp'/name).read_bytes())
    print({'status':'COMPLETE','current_centres':8,'standard_points':256,'qualified':0,'new_experiments':0,'new_accounts':0,
           'artifact':(destination/'review.json').relative_to(base.ROOT).as_posix()})


if __name__=='__main__':
    main()
