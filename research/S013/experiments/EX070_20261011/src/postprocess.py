"""Readable actual-cycle attribution and exact technical-failure lineage; no replay."""
from pathlib import Path
import json
import shutil
import numpy as np
import pandas as pd
import driver

ROOT=driver.ROOT;WORK=driver.WORK
exp,plan,path=driver.stage(); common=driver.oldcommon(); ctx=common.context(1)
complete=driver.read(WORK/'execution_complete.json')
request,result=common.cache_read(WORK/'centre.pkl.gz')
oldrequest,oldresult=driver.native()[0]
assert driver.serialize_evaluation_evidence(request,result)==driver.read(driver.public(complete['reference']))
v=driver.read(WORK/'verification.json'); assert v['status']=='PASS'
new=result.runs[0].execution; old=oldresult.runs[0].execution
altdecisionids=set(new.decisions.loc[new.decisions.alt_only_entry,'decision_id'])
altcycles=set(new.fills.loc[new.fills.side.eq('BUY')&new.fills.decision_id.isin(altdecisionids),'cycle_id'])
account=new.account_daily.copy(); account.index=pd.to_datetime(account.date).dt.normalize()
actual=[]
for trade in new.trades.loc[new.trades.cycle_id.isin(altcycles)].itertuples():
    fills=new.fills.loc[new.fills.cycle_id.eq(trade.cycle_id)]
    cashflow=np.where(fills.side.eq('SELL'),1,-1)*fills.quantity*fills.price-fills.fees
    pricepnl=float((np.where(fills.side.eq('SELL'),1,-1)*fills.quantity*fills.price).sum())
    buy=fills.loc[fills.side.eq('BUY')].iloc[0]
    decision=new.decisions.loc[new.decisions.decision_id.eq(buy.decision_id)].iloc[0]
    actual.append({'cycle_id':trade.cycle_id,'status':trade.status,'entry_signal_date':str(pd.Timestamp(buy.signal_date).date()),
        'entry_date':str(pd.Timestamp(trade.entry_date).date()),'exit_date':str(pd.Timestamp(trade.exit_date).date()),
        'regime':decision.regime,'original_pass':bool(decision.original_pass),'short_alt_pass':bool(decision.short_alt_pass),
        'short_stretch4':float(decision.short_stretch4),'confirmation_score':float(decision.confirmation_score),
        'net_return':float(trade.net_return),'net_pnl':float(cashflow.sum()),'price_pnl':pricepnl,'fees':float(fills.fees.sum())})
assert len(actual)==10 and all(not r['original_pass'] and r['short_alt_pass'] for r in actual)
fills=new.fills.copy(); fills['session']=pd.to_datetime(fills.fill_time).dt.normalize()
altfills=fills.loc[fills.cycle_id.isin(altcycles)].copy()
altfills['cashflow']=np.where(altfills.side.eq('SELL'),1,-1)*altfills.quantity*altfills.price-altfills.fees
altfills['quantity_delta']=np.where(altfills.side.eq('BUY'),1,-1)*altfills.quantity
flows=altfills.groupby('session').cashflow.sum(); shares=altfills.groupby('session').quantity_delta.sum()
groupcash=pd.Series(account.index.map(flows).fillna(0),index=account.index).cumsum()
groupquantity=pd.Series(account.index.map(shares).fillna(0),index=account.index).cumsum()
groupequity=groupcash+groupquantity*account.close
groupfee=pd.Series(account.index.map(altfills.groupby('session').fees.sum()).fillna(0),index=account.index)
groupnet=groupequity.diff(); groupnet.iloc[0]=groupequity.iloc[0]
groupgross=groupnet+groupfee
assert abs(float(groupequity.iloc[-1])-sum(r['net_pnl'] for r in actual))<1e-6
annual={}
for year in sorted(account.index.year.unique()):
    ix=account.index.year==year
    n=v['cash_account']['annual'][str(year)]; b=v['baseline']['cash_account']['annual'][str(year)]
    annual[str(year)]={'new_net_return':n['net_return'],'baseline_net_return':b['net_return'],
        'return_difference_pp':100*(n['net_return']-b['net_return']),
        'new_path_price_pnl':n['price_pnl'],'baseline_path_price_pnl':b['price_pnl'],
        'new_path_fees':n['fees'],'baseline_path_fees':b['fees'],
        'net_pnl_difference':n['net_pnl']-b['net_pnl'],
        'alt_origin_mark_to_market_net_pnl':float(groupnet.loc[ix].sum()),
        'alt_origin_price_pnl':float(groupgross.loc[ix].sum()),'alt_origin_fees':float(groupfee.loc[ix].sum()),
        'alt_origin_actual_buy_fills':int((altfills.side.eq('BUY')&altfills.session.dt.year.eq(year)).sum())}
newdates=set(pd.to_datetime(new.fills.loc[new.fills.side.eq('BUY'),'fill_time']).dt.normalize())
olddates=set(pd.to_datetime(old.fills.loc[old.fills.side.eq('BUY'),'fill_time']).dt.normalize())
doc={'status':'PASS','new_financial_accounts':0,'whole_native_reference':complete['reference'],
    'actual_alternative_cycles':actual,'annual_all_path_and_alt_origin_attribution':annual,
    'actual_buy_date_comparison':{'common':len(newdates&olddates),'baseline_only':len(olddates-newdates),'new_only':len(newdates-olddates),
        'baseline_only_dates':[str(d.date()) for d in sorted(olddates-newdates)],'new_only_dates':[str(d.date()) for d in sorted(newdates-olddates)]},
    'alt_actual_group':{'cycles':len(actual),'winning':sum(r['net_pnl']>0 for r in actual),'losing':sum(r['net_pnl']<0 for r in actual),
        'price_pnl':sum(r['price_pnl'] for r in actual),'fees':sum(r['fees'] for r in actual),'net_pnl':sum(r['net_pnl'] for r in actual),
        'mean_trade_net_return':float(np.mean([r['net_return'] for r in actual]))},
    'limits':'Grouping marks actual alternative-origin cycles; it is not the causal benefit of isolated new trades. New entries alter old-confirmation later paths and account sizes; baseline/new annual percentage differences have distinct opening wealth. Existing known raw30m High/Low discrepancies retained.'}
driver.write(WORK/'attribution.json',doc)
pd.DataFrame(actual).to_csv(WORK/'alternative_cycle_attribution.csv',index=False,float_format='%.17g')
orig=driver.read(path/'protocols/prospective_references.json')
a1=driver.read(path/'protocols/technical_amendment_references.json')
a2=driver.read(path/'protocols/technical_amendment2_references.json')
a3=driver.read(path/'protocols/technical_amendment3_references.json')
failures=[
    {'attempt':'PREACCOUNT_PREFLIGHT_1','driver':orig['driver.py'],'line':148,'assertion':"assert {k:v.to_dict() for k,v in request.input_bindings.items()}==plan['input_bindings']",'exception':'AssertionError'},
    {'attempt':'PREACCOUNT_PREFLIGHT_2','driver':a1['corrected_driver'],'line':155,'assertion':"assert v['plan']['strategy']['runtime_sha256']==candidate.runtime_identity_sha256",'exception':'AssertionError'},
    {'attempt':'PREACCOUNT_PREFLIGHT_3','driver':a2['corrected_driver'],'line':203,'assertion':"'new_parameter_count':14,'new_parameter_plan_status':'NOT_DECLARED_CENTER_ONLY','provider_calls':common.SOURCE_CALLS}",
        'exception':"NameError: name 'common' is not defined. Did you mean: 'oldcommon'?"}]
for r in failures:
    source=Path(driver.public(r['driver'])).read_text(encoding='utf-8')
    assert r['assertion'] in source
    line=source.splitlines()[r['line']-1]
    assert r['assertion'].strip() in line
    r['traceback_excerpt']=f"File '.tmp/s013-short-alt/driver.py', line {r['line']}, in "+('prepared' if r['attempt']!='PREACCOUNT_PREFLIGHT_3' else 'preflight')+'\n    '+r['assertion']+'\n'+r['exception']
technical={'status':'RETAINED_EXACT_PUBLIC_SOURCE_FAILURE_LINEAGE','financial_rule_content_sha256':plan['content_sha256'],
    'original_prospective_reference':orig['plan.json'],'amendment_chain':[a1,a2,a3],
    'failures_before_accounts':failures,'financial_accounts_before_corrections':0,
    'platform_changes':False,'financial_rule_changes':False,
    'publication_sandbox_failure':driver.read(WORK/'technical_failures.json')['failed_attempts'][0],
    'scope':'Exact traceback excerpts captured from tool results paired with hash-verified failed driver line, not reconstructed financial failures.'}
driver.write(WORK/'technical_tracebacks.json',technical)
shutil.copyfile(Path(__file__),path/'src/postprocess.py')
refs={'attribution.json':driver.put(ctx,exp,WORK/'attribution.json'),
    'alternative_cycle_attribution.csv':driver.put(ctx,exp,WORK/'alternative_cycle_attribution.csv'),
    'technical_tracebacks.json':driver.put(ctx,exp,WORK/'technical_tracebacks.json'),
    'postprocess.py':driver.put(ctx,exp,Path(__file__)),
    'final_technical_method':driver.read(path/'protocols/effective_plan3_reference.json')}
driver.write(path/'protocols/postprocessor_references.json',refs)
print(json.dumps({'status':'ACTUAL_ATTRIBUTION_PASS','alt_group':doc['alt_actual_group'],'dates':doc['actual_buy_date_comparison'],'tracebacks':len(failures)},ensure_ascii=False))
