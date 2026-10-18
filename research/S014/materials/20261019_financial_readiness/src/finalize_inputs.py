"""Join independently reconciled originals to pinned observations and clocks.

This publishes admissible input facts and dependency checks, not F1/F2 signals,
return labels, forecasts, or account results. Missing observations remain null.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[5]
OUT=Path(__file__).resolve().parents[1]
MAIN={'income':{'revenue','oper_cost','n_income'},'balancesheet':{'total_assets'},'cashflow':{'n_cashflow_act'}}


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8')


def main():
    prep=read(OUT/'others/preparation.json')
    audit=read(OUT/'others/original_acceptance.json')
    clocks=read(OUT/'others/disclosure_clock_and_dependencies.json')
    assert prep['status']=='READY' and prep['reference']==audit['preparation_reference']==clocks['reference']
    assert audit['checks_total']==297 and audit['periods_total']==33
    inv=read(OUT/'official/inventory_v2.json')
    catalogue=read(OUT/'official/catalogue_validation_v2.json')
    assert catalogue['union_matches_reported_total'] and catalogue['later_date_partitions_complete']
    assert len({doc['period'] for doc in inv['documents']})==33
    for doc in inv['documents']:
        assert digest(ROOT/doc['pdf_path'])==doc['sha256']
        assert digest(ROOT/doc['text_path'])==doc['text_sha256']
    for source in audit['source_manifest']:
        assert digest(ROOT/source['path'])==source['sha256']
    frames={}
    for item in prep['items']:
        assert digest(ROOT/item['csv_path'])==item['csv_sha256']
        frames[item['kind']]=pd.read_csv(ROOT/item['csv_path'],dtype={'end_date':str,'RecordId':str})
    raw_cal=read(OUT/'upstream/responses/trade_cal.json')
    calendar=pd.DataFrame(raw_cal['items'],columns=raw_cal['fields'])
    sessions=sorted(pd.to_datetime(calendar.loc[calendar.is_open.astype(int).eq(1),'cal_date'],format='%Y%m%d'))
    def available(day):
        return next(session for session in sessions if session>pd.Timestamp(day))+pd.Timedelta(hours=15)
    facts=[]
    by_key={}
    for check in audit['checks']:
        kind,period,field=check['kind'],check['period'],check['field']
        observations=check['observations']
        assert all(not observation['ann_date_precedes_matching_original'] for observation in observations)
        matched=[observation for observation in observations if observation['status']=='PUBLIC_ORIGINAL_RECONCILED']
        values={Decimal(str(observation['value'])) for observation in matched}
        assert len(values)<=1
        raw_frame=frames[kind]
        matched_ids=[]
        for observation in matched:
            ids=raw_frame.loc[raw_frame.RecordId.str.split(':').str[0].eq(observation['raw_record_sha256']),'RecordId'].tolist()
            assert ids,(kind,period,field,'Observation not found in pinned DFLS content')
            matched_ids.extend(ids)
        is_main=field in MAIN.get(kind,set())
        if not matched:
            assert (period,kind,field)==('20180930','balancesheet','accounts_receiv')
            assert check['status']=='NOT_SEPARATELY_DISCLOSED_SCOPE'
            fact={'period':period,'kind':kind,'field':field,'value':None,'state':'NOT_SEPARATELY_DISCLOSED',
                  'mechanism_role':'COMPETING_EXPLANATION_ONLY','eligible_observation_ids':[],
                  'original_scope':'NOTES_AND_ACCOUNTS_RECEIVABLE_COMBINED_NOT_SEPARABLE',
                  'original_combined_value_cny':check['scope_evidence'][0]['value_cny'],
                  'scope_evidence':[{'pdf_sha256':evidence['pdf_sha256'],'pdf_path':evidence['pdf_path'],
                                     'page':evidence['page'],'publication_date':evidence['publication_date']}
                                    for evidence in check['scope_evidence']],
                  'null_policy':'SOURCE_NULL_PRESERVED_NO_ZERO_FILL_OR_INFERRED_SPLIT'}
        else:
            originals=[match for observation in matched for match in observation['matches'] if match['context_verified']]
            first=min(originals,key=lambda match:(match['publication_date'],match['doc_id'],match['page']))
            anchor=max([first['publication_date']]+[observation[name][:4]+'-'+observation[name][4:6]+'-'+observation[name][6:]
                for observation in matched for name in ('ann_date','f_ann_date') if observation.get(name)])
            public_available=available(anchor)
            assert raw_frame.loc[raw_frame.RecordId.isin(matched_ids),'AvailableDate'].map(pd.Timestamp).ge(public_available).all()
            fact={'period':period,'kind':kind,'field':field,'value':float(next(iter(values))),
                  'state':'PUBLIC_ORIGINAL_VALUE_RECONCILED','mechanism_role':'MAIN_F1_F2' if is_main else 'ATTRIBUTION_OR_COMPETING_EXPLANATION',
                  'eligible_observation_ids':sorted(set(matched_ids)),
                  'source_null_observation_rows_preserved':sum(observation['value'] is None for observation in observations),
                  'public_support_date_in_scoped_corpus':first['publication_date'],
                  'effective_date_anchor':anchor,'decision_available_at':public_available.isoformat(),
                  'earliest_execution_session':next(session for session in sessions if session>public_available.normalize()).strftime('%Y-%m-%d'),
                  'original_source':{key:first[key] for key in ('pdf_path','pdf_sha256','doc_id','publication_date','url','page','last_page',
                        'section_heading','selected_numeric_column_1based','scope','currency','unit','period_basis','text_sha256')},
                  'null_policy':'DO_NOT_FILL_SOURCE_ROWS; admissible nonnull value independently proven by this original',
                  'version_policy':'No update_flag preference; first matching original in declared corpus; no backward revised-value filling'}
        facts.append(fact)
        by_key[(kind,period,field)]=fact
    dependencies=[]
    for event in clocks['dependencies']:
        current=[]
        for kind,fields in MAIN.items():
            for field in fields:
                current.append(by_key[(kind,event['target_period'],field)])
        event_available=max(fact['decision_available_at'] for fact in current)
        proofs=[]
        for requirement in event['required_original_record_periods']:
            for field in MAIN[requirement['kind']]:
                fact=by_key[(requirement['kind'],requirement['period'],field)]
                assert fact['state']=='PUBLIC_ORIGINAL_VALUE_RECONCILED'
                assert fact['decision_available_at']<=event_available
                proofs.append({'kind':fact['kind'],'period':fact['period'],'field':field,
                    'original_pdf_sha256':fact['original_source']['pdf_sha256'],
                    'original_page':fact['original_source']['page'],'available_at':fact['decision_available_at'],
                    'eligible_observation_ids':fact['eligible_observation_ids']})
        dependencies.append({'target_period':event['target_period'],'role':event['role'],
            'decision_available_at':event_available,'status':'MAIN_INPUT_ORIGINALS_AVAILABLE_NO_LATER_THAN_DECISION',
            'dependency_proofs':proofs})
    assert dependencies[0]['target_period']=='20190930' and dependencies[0]['decision_available_at']<'2020-01-01'
    requests=list((OUT/'upstream/attempts').glob('*.json'))
    assert len(requests)==5 and all(read(path)['status']=='RECEIVED' for path in requests)
    status_counts=Counter(fact['state'] for fact in facts)
    result={'status':'READY_FOR_STAGE_TWO_PUBLIC_FINANCIAL_INFORMATION_RESEARCH_WITH_DECLARED_LIMITS',
        'created_utc':datetime.now(timezone.utc).isoformat(),'batch':'S014','symbol':'600722.SH',
        'evaluation_window':['2020-01-01','2026-10-15'],'preparation_reference':prep['reference'],
        'original_audit_path':(OUT/'others/original_acceptance.json').relative_to(ROOT).as_posix(),
        'original_audit_sha256':digest(OUT/'others/original_acceptance.json'),
        'source_preparation_sha256':digest(OUT/'others/preparation.json'),
        'scope':{'report_periods':33,'evaluation_report_periods':27,'prewindow_report_periods':6,
            'core_field_period_cells':len(facts),'cell_status_counts':dict(status_counts),
            'raw_observation_rows':sum(len(frame) for frame in frames.values()),
            'actual_financial_and_calendar_calls':len(requests),'actual_catalogue_requests':16,
            'actual_pdf_requests':len(list((OUT/'official/requests/pdf').glob('*.request.json')))},
        'time_contract':{'source_date':'max(upstream ann_date, f_ann_date, supporting official publication date)',
            'decision':'first strictly later SSE session at 15:00 Asia/Shanghai','execution':'following SSE session',
            'historical_vendor_arrival_verified':False,'unobserved_revision_history_complete':False,
            'meaning':'Reconciled public original financial facts under an explicit conservative date policy; not certified historical vendor snapshots'},
        '2018_annual_revision':'2019-02-13 original and 2019-03-05 revision have identical 9 core fields; notice corrects missing share capital and capital reserve, not these core fields',
        'use_rules':['Read the pinned DFLS observations and restrict numeric inputs to this manifest eligible_observation_ids',
            'Respect per-field decision_available_at, report-period/accounting scope and all original source hashes',
            'Preserve all raw nulls and duplicates; 2025H1 deducted-profit null row must not be filled or called a fully certified vintage',
            '2018Q3 receivable-only comparison unavailable; do not use combined notes/receivables as the same variable',
            'Same-day releases are one information cluster; forward filling does not increase independent sample count',
            'Historical sample remains seen development data; no new independent holdout is created',
            'Financial signal definition, return-label protocol and actual stage-two execution are the next task, not results of this manifest'],
        'facts':facts,'event_dependency_proofs':dependencies,
        'new_return_labels':0,'new_fits':0,'new_account_experiments':0,'historical_candidate_eligibility_changed':False}
    assert status_counts=={'PUBLIC_ORIGINAL_VALUE_RECONCILED':296,'NOT_SEPARATELY_DISCLOSED':1}
    write(OUT/'others/accepted_financial_inputs.json',result)
    print(json.dumps({'status':result['status'],'scope':result['scope'],'dependency_events':len(dependencies)},ensure_ascii=True))


if __name__=='__main__':
    main()
