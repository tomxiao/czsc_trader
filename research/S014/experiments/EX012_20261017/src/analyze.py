"""Unmask only after immutable annotations exist; descriptive contrasts only."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.research_tools import EvidenceRef

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def calculate():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    refs=read(EX/'protocols/published_annotations.json')
    ref=EvidenceRef.from_dict(refs['annotations'])
    raw=ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest()==ref.sha256
    assert raw==(EX/'protocols/annotations.json').read_bytes()
    annotations=json.loads(raw)
    lock=read(EX/'protocols/annotation_lock.json')
    assert lock['outcomes_unmasked'] is False and lock['annotations']==ref.to_dict()
    sample_ref=EvidenceRef.from_dict(read(EX/'protocols/published_sample.json')['sealed-outcomes'])
    raw=sample_ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest()==sample_ref.sha256
    outcomes=json.loads(raw)
    ann_by_case={c['case_id']:c for c in annotations['cases']}
    docs={d['doc_id']:d for d in annotations['documents']}
    cases=[{**c,**ann_by_case[c['case_id']]} for c in outcomes['cases']]
    pairs=[]
    for anchor in sorted({c['anchor'] for c in cases}):
        group={c['group']:c for c in cases if c['anchor']==anchor}
        win,loss=group['repair_positive'],group['repair_nonpositive']
        pairs.append({'anchor':anchor,'positive':win['case_id'],'nonpositive':loss['case_id'],
            'positive_return':win['net_return'],'nonpositive_return':loss['net_return'],
            'same_window_financial_events':win['financial_events_in_window']==loss['financial_events_in_window'],
            'positive_financial_events':win['financial_events_in_window'],'nonpositive_financial_events':loss['financial_events_in_window'],
            'same_observed_report':win['last_observed_report'] is not None and win['last_observed_report']==loss['last_observed_report'],
            'positive_observed_report':win['last_observed_report'],'nonpositive_observed_report':loss['last_observed_report'],
            'stock_prediction_ranks_positive_higher':win['prediction_ridge_stock']>loss['prediction_ridge_stock'],
            'market_prediction_ranks_positive_higher':win['prediction_ridge_market']>loss['prediction_ridge_market'],
            'other_positive_events': sorted({docs[d]['event_key'] for d in win['usable_reviewed'] if docs[d]['category']!='EARNINGS_OPERATING'}),
            'other_nonpositive_events': sorted({docs[d]['event_key'] for d in loss['usable_reviewed'] if docs[d]['category']!='EARNINGS_OPERATING'})})
    return {'annotation_ref':ref.to_dict(),'outcomes_ref':sample_ref.to_dict(),'cases':cases,'pairs':pairs,
        'counts':{'cases':len(cases),'repair_pairs':len(pairs),'ordinary_controls':sum(c['group']=='ordinary' for c in cases),
            'same_window_financial_pairs':sum(p['same_window_financial_events'] for p in pairs),
            'same_observed_report_pairs':sum(p['same_observed_report'] for p in pairs),
            'cases_with_same_day_time_unknown':sum(bool(c['same_day_time_unknown']) for c in cases),
            'cases_with_post_decision_documents':sum(bool(c['post_decision']) for c in cases),
            'stock_correct_pair_rank':sum(p['stock_prediction_ranks_positive_higher'] for p in pairs),
            'market_correct_pair_rank':sum(p['market_prediction_ranks_positive_higher'] for p in pairs)},
        'interpretation':'描述性配对，不计算抽样后的成功率/策略收益/显著性，不拟合公告规则；日期可用不代表分钟、初次披露与历史版本已验证。'}


def main():
    p=EX/'others/analysis.json'
    if p.exists():raise RuntimeError('Preserve first unmask result')
    result=calculate()
    result['unmasked_at_utc']=datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'counts':result['counts'],'pairs':result['pairs'],'cases':[{k:c[k] for k in ('case_id','signal_date','group','net_return','last_observed_report','same_day_time_unknown')} for c in result['cases']]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
