"""Offline pinned-input, dependency and disclosure-clock checks; no signals/labels."""
from dataclasses import replace
import json
from pathlib import Path
from uuid import UUID

import pandas as pd

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import (DataRequest, DataStatus, Dataset, FinancialDisclosureParameters, FinancialReportKind,
                       PreparedDataRef, ProviderBinding, ProviderConfig)

ROOT=Path(__file__).resolve().parents[5]
OUT=Path(__file__).resolve().parents[1]
CORE={'income':['revenue','oper_cost','n_income','n_income_attr_p'],
      'balancesheet':['total_assets','accounts_receiv','inventories'],
      'cashflow':['n_cashflow_act'],'fina_indicator':['profit_dedt']}


def read(path):
    return json.loads(path.read_bytes())


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8')


def main():
    prep=read(OUT/'others/preparation.json')
    assert prep['status']=='READY'
    ref=PreparedDataRef(UUID(prep['reference']['space_id']),UUID(prep['reference']['preparation_id']),prep['reference']['manifest_sha256'])
    def offline_only(request):
        raise AssertionError('Pinned validation must never acquire a source')
    context=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),
        providers=ProviderConfig(bindings={Dataset.COMPANY_FINANCIAL_DISCLOSURES:
            ProviderBinding('offline-read-only','v1',offline_only)}))
    periods=tuple(pd.period_range('2018Q2','2026Q2',freq='Q-DEC').end_time.strftime('%Y-%m-%d'))
    frames={}
    series={}
    ledger=[]
    checks=[]
    for kind in FinancialReportKind:
        query=DataRequest(Dataset.COMPANY_FINANCIAL_DISCLOSURES,'600722.SH','2018-07-01','2026-10-15',None,
             frequency='event',parameters=FinancialDisclosureParameters(kind,'2018-06-30','2026-06-30',
             **({'report_type':None} if kind is FinancialReportKind.FINANCIAL_INDICATOR else {}),expected_periods=periods))
        result=context.data.fetch(query,prepared=ref)
        assert result.ready,result.error
        item=next(item for item in prep['items'] if item['kind']==kind.value)
        assert result.identity.content_sha256==item['content_sha256']
        frames[kind.value]=result.dataframe
        checks.append({'check':'pinned_content_identity','kind':kind.value,'passed':True,'rows':len(result.dataframe),'sha256':result.identity.content_sha256})
        # Validate a properly bounded event read without imposing all 33 periods.
        # Financial expected_periods is selection identity, so use the full selected
        # period contract here and separately inspect clipped rows for time bounds.
        assert pd.to_datetime(result.dataframe.Date).between('2018-07-01','2026-10-15').all()
        assert result.dataframe.RecordId.nunique()==len(result.dataframe)
        assert not result.identity.metadata['historical_vendor_arrival_verified']
        for period,group in result.dataframe.groupby('end_date',sort=True):
            dates=sorted(set(pd.to_datetime(group.Date).dt.strftime('%Y-%m-%d')))
            available=sorted(set(pd.to_datetime(group.AvailableDate).dt.strftime('%Y-%m-%dT%H:%M:%S')))
            record={'kind':kind.value,'period':str(period),'announcement_dates':dates,'decision_available_at':available,
                    'observed_record_ids':group.RecordId.tolist(),'raw_version_selection':'NONE_ALL_ROWS_PRESERVED','core':{}}
            for field in CORE[kind.value]:
                values=sorted(set(group[field].dropna().tolist()))
                assert len(values)<=1,(kind.value,period,field,values)
                record['core'][field]={'observed_value':values[0] if values else None,
                    'null_rows':int(group[field].isna().sum()),'nonnull_alternative_values':len(values)}
            series[(kind.value,str(period))]=record
            ledger.append(record)
        # An out-of-scope request must remain rejected on the pinned asset.
        rejected=context.data.fetch(replace(query,end='2026-10-16'),prepared=ref)
        assert rejected.status is DataStatus.FAILED and rejected.error.code=='REQUEST_NOT_PREPARED'
        checks.append({'check':'reject_unprepared_expansion','kind':kind.value,'passed':True})
    all_periods=sorted({str(period) for period in frames['income'].end_date})
    target=[pd.Period(pd.Timestamp(p),freq='Q-DEC') for p in all_periods if p>='20191231']
    target.insert(0,pd.Period('2019Q3',freq='Q-DEC'))
    dependencies=[]
    for period in target:
        required={period,period-4}
        for current in (period,period-4):
            required.add(current-1)  # previous quarter assets; YTD flow differencing except Q1
        end=period.end_time.strftime('%Y%m%d')
        event_dates=[date for (api,p),row in series.items() if p==end for date in row['decision_available_at']]
        assert event_dates
        decision=max(event_dates)
        necessary=[]
        for quarter in sorted(required):
            p=quarter.end_time.strftime('%Y%m%d')
            for api,fields in [('income',['revenue','oper_cost','n_income']),('balancesheet',['total_assets']),('cashflow',['n_cashflow_act'])]:
                row=series[(api,p)]
                assert all(row['core'][field]['observed_value'] is not None for field in fields)
                earlier=[date for date in row['decision_available_at'] if date<=decision]
                assert earlier,(period,api,p,'No available original observation at decision')
                necessary.append({'kind':api,'period':p,'available_no_later_than_event':earlier})
        dependencies.append({'target_period':end,'role':'INITIAL_STATE' if end=='20190930' else 'EVALUATION_DISCLOSURE',
            'combined_current_decision_available_at':decision,'required_original_record_periods':necessary,
            'status':'OBSERVED_DEPENDENCIES_PRESENT_PENDING_ORIGINAL_AUDIT','no_financial_signal_or_return_computed':True})
    evaluation_dates=sorted({date for row in ledger if row['period']>='20191231' for date in row['announcement_dates']})
    # The initial state used at 2020 start must already have been public by then.
    assert dependencies[0]['combined_current_decision_available_at']<'2020-01-01'
    calendar=read(OUT/'upstream/responses/trade_cal.json')
    cal=pd.DataFrame(calendar['items'],columns=calendar['fields'])
    cal['day']=pd.to_datetime(cal.cal_date,format='%Y%m%d')
    assert cal.day.is_unique
    assert sorted(cal.cal_date.astype(str))==pd.date_range('2018-06-30','2026-11-24').strftime('%Y%m%d').tolist()
    open_days=sorted(cal.loc[cal.is_open.astype(int).eq(1),'day'])
    for row in ledger:
        for date,decision in zip(row['announcement_dates'],row['decision_available_at']):
            expected=next(day for day in open_days if day>pd.Timestamp(date))+pd.Timedelta(hours=15)
            assert expected==pd.Timestamp(decision)
    write(OUT/'others/disclosure_clock_and_dependencies.json',{'status':'OBSERVED_INPUT_CHECKS_PASS_ORIGINAL_AUDIT_SEPARATE',
        'reference':prep['reference'],'read_new_api_calls':0,'calendar_rows':len(cal),'periods':len(all_periods),
        'evaluation_periods':len(target)-1,'distinct_evaluation_disclosure_dates':len(evaluation_dates),
        'same_day_clustering_required':True,'checks':checks,'ledger':ledger,'dependencies':dependencies,
        'limits':['No new return labels, financial signals, model fits or accounts',
                  'Source version rows and nulls preserved; numeric equivalence is not a historical vintage proof',
                  'Official original-document audit and upstream observation identity must be used together',
                  'Historical supplier arrival remains unknown; availability is a conservative public-date policy']})
    print(json.dumps({'status':'PASS','periods':33,'evaluation_periods':27,'initial_state':'2019Q3',
                      'evaluation_disclosure_dates':len(evaluation_dates),'raw_records':len(ledger),'checks':len(checks),
                      'new_api_calls':0},ensure_ascii=True))


if __name__=='__main__':
    main()
