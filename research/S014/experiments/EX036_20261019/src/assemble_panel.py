"""Join the fixed financial state and all event labels without sample selection."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def main():
    assert not (EX/'others/event_panel.csv').exists()
    for rel,ref in read(EX/'protocols/published_design.json').items():
        assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes()==(ROOT/rel).read_bytes()
    features=pd.read_csv(EX/'others/financial_features.csv',dtype={'report_period':str,'decision_date':str})
    labels=pd.read_csv(EX/'others/market_event_labels.csv',dtype={'report_period':str,'decision_date':str})
    assert len(features)==len(labels)==25
    assert not features.decision_date.duplicated().any() and not labels.decision_date.duplicated().any()
    assert features.set_index('decision_date').report_period.equals(labels.set_index('decision_date').report_period)
    features=features.rename(columns={'event_id':'feature_event_id'})
    labels=labels.rename(columns={'price_endpoint_date':'price_end_date','stock_return20':'return20'})
    panel=features.merge(labels.drop(columns='report_period'),on='decision_date',how='outer',validate='one_to_one',indicator=True)
    assert len(panel)==25 and panel['_merge'].eq('both').all()
    panel=panel.drop(columns='_merge').sort_values('decision_date').reset_index(drop=True)
    assert panel.price_label_status.eq('COMPLETE').all()
    assert panel[['F1','F2','PARENT','return20','sector_excess_return20','mae20','stock_trailing20','sector_trailing20']].notna().all().all()
    assert set(panel.execution_status)=={'CLOSED','NO_TRADE'}
    assert panel.loc[panel.execution_status.eq('NO_TRADE'),'net_position_return'].isna().all()
    assert panel.loc[panel.execution_status.eq('CLOSED'),'net_position_return'].notna().all()
    assert int(panel.joint_report_count.sum())==27
    # Earlier bounded forecast observations may flag prior public information;
    # no return is computed from them and missing observations are UNKNOWN.
    forecast_path=ROOT/'research/S014/materials/20261018_financial_feasibility/responses/call_05.json'
    source=read(forecast_path)
    forecast=pd.DataFrame(source['items'],columns=source['fields'])
    flags=[]
    matches=[]
    for row in panel.itertuples():
        earlier=forecast.loc[forecast.end_date.astype(str).eq(str(row.report_period)) &
            forecast.ann_date.astype(str).le(row.decision_date.replace('-',''))]
        flags.append(True if len(earlier) else None)
        matches.append('|'.join(sorted(set(earlier.ann_date.astype(str)))))
    panel['prior_guidance_observed_unverified']=flags
    panel['prior_guidance_dates_unverified']=matches
    assert all(flag is True or flag is None for flag in flags)
    panel.to_csv(EX/'others/event_panel.csv',index=False,lineterminator='\n')
    notes={'status':'PASS','events':25,'reports':27,'price_complete':25,
        'execution_counts':panel.execution_status.value_counts().to_dict(),
        'F1_positive':int(panel.F1.sum()),'F2_positive':int(panel.F2.sum()),'PARENT_positive':int(panel.PARENT.sum()),
        'source_sha256':{name:sha256((EX/'others'/name).read_bytes()).hexdigest() for name in
            ['financial_features.csv','financial_features_lineage.json','market_event_labels.csv','market_inputs.json','market_label_checks.json']},
        'event_panel_sha256':sha256((EX/'others/event_panel.csv').read_bytes()).hexdigest(),
        'forecast_source_sha256':sha256(forecast_path.read_bytes()).hexdigest(),
        'known_prior_guidance_events':sum(flag is True for flag in flags),
        'prior_guidance_absence':'UNKNOWN_NOT_A_ZERO_FEATURE; vendor original guidance history not certified; no F3 model',
        'implementation_clarifications':['Each comparison group needs at least2 contributing dependence blocks for a95% descriptive bootstrap interval; otherwise effect description retained and CI unavailable',
            'event_id=market FIN_YYYYMMDD; feature_event_id preserves original FIN01..FIN25 mapping',
            'price_end_date is market price_endpoint_date; return20 is market stock_return20; no values changed',
            'NO_TRADE keeps null position return; all complete price labels remain in primary population',
            'This panel has25 event rows, not25 independent nonoverlapping outcomes; block dependence is handled in statistics'],
        'new_api_calls':0,'new_continuous_accounts':0}
    with (EX/'others/panel_precheck.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(notes,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({key:notes[key] for key in ('status','events','execution_counts','known_prior_guidance_events','event_panel_sha256')}))


if __name__=='__main__':
    main()
