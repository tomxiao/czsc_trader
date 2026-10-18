"""Offline data availability and integrity checks; no signal/model/account returns."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]
START, END = '20200101', '20261015'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def frame(i):
    raw = read(OUT / f'responses/call_{i:02d}.json')
    return pd.DataFrame(raw['items'], columns=raw['fields'])

def dates(values):
    return pd.to_datetime(values.astype(str), format='mixed').dt.strftime('%Y%m%d')

def quality(df):
    x = df.copy()
    x['trade_date'] = dates(x.trade_date)
    numeric = [c for c in x if c not in ['ts_code','trade_date']]
    numeric_bad = {c:int((~np.isfinite(pd.to_numeric(x[c],errors='coerce'))).sum()) for c in numeric}
    prices = x[['open','high','low','close','settle','pre_close','pre_settle']].astype(float)
    bounds = ((prices.high < prices[['open','close','low']].max(axis=1)) |
              (prices.low > prices[['open','close','high']].min(axis=1)))
    return {'rows':len(x),'duplicate_date_symbol':int(x.duplicated(['ts_code','trade_date']).sum()),
        'outside_window':int(((x.trade_date < START)|(x.trade_date > END)).sum()),
        'nonfinite_by_field':numeric_bad, 'ohlc_bounds_violations':int(bounds.sum()),
        'nonpositive_price_cells':int((prices <= 0).sum().sum()),
        'negative_vol_amount_oi_cells':int((x[['vol','amount','oi']].astype(float)<0).sum().sum()),
        'zero_volume_rows':int(x.vol.eq(0).sum()),
        'change1_identity_mismatch':int((~np.isclose(x.change1, x.close-x.pre_settle)).sum()),
        'change2_identity_mismatch':int((~np.isclose(x.change2, x.settle-x.pre_settle)).sum())}

def main():
    receipts = [read(p) for p in sorted((OUT/'attempts').glob('call_*.json'))]
    assert len(receipts) == sum(r['http_requests'] for r in receipts) == 8
    assert all(r['status']=='RECEIVED' and r['vendor_code']==0 and r['http_status']==200 for r in receipts)
    manifest=[]
    for r in receipts:
        for key in ['response','csv']:
            p=ROOT/r[key+'_path']; assert sha256(p.read_bytes()).hexdigest()==r[key+'_sha256']
            manifest.append({'path':r[key+'_path'],'sha256':r[key+'_sha256']})
    basic,mapping,daily,cal=[frame(i) for i in range(1,5)]
    for f in [mapping,daily]: f['trade_date']=dates(f.trade_date)
    cal['cal_date']=dates(cal.cal_date); cal=cal.sort_values('cal_date')
    expected_cal=set(pd.date_range('2020-01-01','2026-10-15').strftime('%Y%m%d'))
    opens=cal[cal.is_open.astype(int).eq(1)].copy()
    expected=set(opens.cal_date)
    previous=dates(opens.pretrade_date).tolist()
    predecessor_errors=sum(a != b for a,b in zip(previous[1:],opens.cal_date.tolist()[:-1]))
    s014_source=ROOT/'research/S014/experiments/EX030_20261018/others/features.csv'
    s014=pd.read_csv(s014_source,usecols=['date'])
    s014_dates=dates(s014.date); s014_set=set(s014_dates[(s014_dates>=START)&(s014_dates<=END)])
    coverage={}
    for name,df in [('mapping',mapping),('continuous_daily',daily)]:
        got=set(df.trade_date)
        coverage[name]={'rows':len(df),'unique_days':len(got),
            'missing_open_dates':sorted(expected-got),'extra_dates':sorted(got-expected),
            'duplicates':int(df.duplicated(['ts_code','trade_date']).sum()),
            'wrong_symbols':sorted(set(df.ts_code)-{'MA.ZCE'}),
            'counts_by_year':df.trade_date.str[:4].value_counts().sort_index().to_dict()}
    ordinary=basic[basic.ts_code.str.match(r'MA\d{4}\.ZCE$')].copy()
    ordinary['list_date']=dates(ordinary.list_date);ordinary['delist_date']=dates(ordinary.delist_date)
    directory=ordinary.set_index('ts_code')
    mapping=mapping.sort_values('trade_date').reset_index(drop=True)
    lookup=mapping.merge(ordinary[['ts_code','list_date','delist_date']],left_on='mapping_ts_code',right_on='ts_code',how='left')
    active_bad=lookup[(lookup.list_date.isna())|(lookup.trade_date<lookup.list_date)|(lookup.trade_date>lookup.delist_date)]
    rolls=mapping.loc[mapping.mapping_ts_code.ne(mapping.mapping_ts_code.shift())].copy()
    rolls['prior_contract']=mapping.mapping_ts_code.shift().loc[rolls.index]
    rolls=rolls.iloc[1:]
    comparison=[]; samples=[]; all_raw=[]
    compare_fields=['open','high','low','close','settle','pre_close','pre_settle','vol','amount','oi']
    for i in range(5,9):
        raw=frame(i);raw['trade_date']=dates(raw.trade_date);all_raw.append(raw)
        symbol=receipts[i-1]['params']['ts_code']; info=directory.loc[symbol]
        expected_raw={d for d in expected if info.list_date<=d<=info.delist_date}
        got=set(raw.trade_date)
        selected=mapping[mapping.mapping_ts_code.eq(symbol)][['trade_date']].merge(daily,on='trade_date')
        pair=selected.merge(raw,on='trade_date',suffixes=('_main','_raw'),how='outer',indicator=True)
        matched=pair[pair['_merge'].eq('both')]
        mismatches={c:int((~np.isclose(matched[c+'_main'],matched[c+'_raw'],equal_nan=False)).sum()) for c in compare_fields}
        mismatch_rows=[]
        for c in compare_fields:
            bad=matched.loc[~np.isclose(matched[c+'_main'],matched[c+'_raw'],equal_nan=False)]
            for _,row in bad.iterrows():
                mismatch_rows.append({'trade_date':row.trade_date,'field':c,
                    'continuous':float(row[c+'_main']),'raw_contract':float(row[c+'_raw'])})
        comparison.append({'contract':symbol,'mapped_dates':len(selected),'matched_dates':len(matched),
            'missing_mapped_dates':sorted(set(selected.trade_date)-got),'field_mismatches':mismatches,
            'mismatch_rows':mismatch_rows})
        zero_rows=raw.loc[raw.vol.eq(0), ['ts_code','trade_date','open','high','low','close','settle','vol','oi']]
        missing_preclose_dates=raw.loc[raw.pre_close.isna(),'trade_date'].tolist()
        samples.append({'call':i,'contract':symbol,'list_date':info.list_date,'delist_date':info.delist_date,
            'expected_days_in_scope':len(expected_raw),'rows':len(raw),'missing_dates':sorted(expected_raw-got),
            'extra_dates':sorted(got-expected_raw),'quality':quality(raw),
            'zero_volume_rows':zero_rows.to_dict('records'),'missing_preclose_dates':missing_preclose_dates})
    raw_all=pd.concat(all_raw).set_index(['ts_code','trade_date'])
    d=daily.set_index('trade_date').sort_index()
    lastroll=rolls.iloc[-1]; day=lastroll.trade_date
    prev=opens[opens.cal_date.eq(day)].iloc[0].pretrade_date
    prev=pd.Timestamp(str(prev)).strftime('%Y%m%d')
    old,new=lastroll.prior_contract,lastroll.mapping_ts_code
    # Pure identity check for stitched prices; no future outcome/model evaluation.
    roll_example={'trade_date':day,'previous_trade_date':prev,'old_contract':old,'new_contract':new,
        'old_previous_close':float(raw_all.loc[(old,prev),'close']),
        'new_previous_close':float(raw_all.loc[(new,prev),'close']),
        'new_current_close':float(raw_all.loc[(new,day),'close']),
        'main_previous_close':float(d.loc[prev,'close']),
        'main_current_close':float(d.loc[day,'close']),
        'main_pre_close_field':float(d.loc[day,'pre_close'])}
    roll_example['raw_contract_previous_close_matches_pre_close']=bool(np.isclose(
        roll_example['new_previous_close'],roll_example['main_pre_close_field']))
    roll_example['between_contract_price_gap']=roll_example['new_previous_close']-roll_example['old_previous_close']
    roll_dates=set(rolls.trade_date)
    preclose_mismatch=[]
    for k in range(1,len(d)):
        if not np.isclose(d.pre_close.iloc[k],d.close.iloc[k-1]):preclose_mismatch.append(d.index[k])
    covered=sum(x['matched_dates'] for x in comparison)
    chosen={s['contract'] for s in samples}
    remaining=sorted(set(mapping.mapping_ts_code)-chosen)
    result={'status':'COMPLETE_FEASIBILITY_CHECK','scope':'No model, signal, or account experiment',
        'actual_calls':8,'failed_calls':0,'remaining_calls':0,'permission':'VERIFIED_FOR_REQUESTED_ENDPOINTS',
        'calendar':{'rows':len(cal),'open_days':len(expected),'missing_calendar_dates':sorted(expected_cal-set(cal.cal_date)),
            'extra_calendar_dates':sorted(set(cal.cal_date)-expected_cal),'duplicates':int(cal.cal_date.duplicated().sum()),
            'exchange_values':sorted(cal.exchange.unique().tolist()),'open_day_predecessor_errors':predecessor_errors,
            'S014_session_missing':sorted(s014_set-expected),'S014_session_extra':sorted(expected-s014_set)},
        'coverage':coverage,'continuous_quality':quality(daily),
        'directory':{'rows':len(basic),'ordinary_contracts':len(ordinary),'mapped_contracts':int(mapping.mapping_ts_code.nunique()),
            'mapped_outside_contract_validity':active_bad.to_dict('records'),
            'missing_trade_time_desc':int(basic.trade_time_desc.isna().sum())},
        'roll_count':len(rolls),'continuous_pre_close_not_previous_continuous_close':{
            'count':len(preclose_mismatch),'on_roll_dates':len(set(preclose_mismatch)&roll_dates),
            'non_roll_dates':sorted(set(preclose_mismatch)-roll_dates)},
        'sampled_contracts':samples,'raw_mapping_comparison':comparison,'latest_roll_example':roll_example,
        'raw_contract_coverage':{'checked_contracts':len(chosen),'total_mapped_contracts':int(mapping.mapping_ts_code.nunique()),
            'checked_mapped_days':covered,'total_mapped_days':len(mapping),'remaining_contracts':remaining,
            'raw_full_history_verified':False,
            'additional_single_contract_calls_estimate':len(remaining),
            'estimate_scope':'one request per remaining mapped contract, nominal below 2000 rows; failures, extra prewindow, full-universe OI and retries excluded; not authorized'},
        'point_in_time':{'same_day_at_1500':'NOT_SUPPORTED_BY_DOCUMENTED_UPDATE_TIMING',
            'historical_first_availability':'UNVERIFIED','historical_revisions':'UNVERIFIED',
            'mapping_publication_and_selection_cutoff':'UNVERIFIED',
            'lagged_daily_use':'POSSIBLE_DECLARED_CONVENTION_ONLY_NOT_STRICT_PIT',
            'first_session_prior_day_not_requested':'2019-12-31'},
        'formal_prepared_data':False,'new_models':0,'new_accounts':0,
        'input_manifest':manifest,'existing_S014_calendar_reference':{'path':s014_source.relative_to(ROOT).as_posix(),
            'sha256':sha256(s014_source.read_bytes()).hexdigest(),'only_date_column_read':True}}
    (OUT/'others').mkdir(exist_ok=True)
    (OUT/'others/analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    rolls.to_csv(OUT/'others/roll_dates.csv',index=False,lineterminator='\n')
    compact={k:v for k,v in result.items() if k not in ['input_manifest','sampled_contracts']}
    compact['sample_summary']=[{k:v for k,v in x.items() if k!='quality'} for x in samples]
    print(json.dumps(compact,ensure_ascii=False))

if __name__=='__main__':main()
