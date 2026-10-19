"""Fixed, as-of F1/F2 definitions; no price labels or fitted parameters."""
from collections import defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path
import socket
from uuid import UUID

import pandas as pd

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef
from dataflows import (DataRequest, Dataset, FinancialDisclosureParameters, FinancialReportKind,
                       PreparedDataRef, ProviderConfig)

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
READY=ROOT/'research/S014/materials/20261019_financial_readiness'


def read(path):
    return json.loads(path.read_bytes())


def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def build_financial_features(accepted):
    """Construct one latest-known financial state per disclosure-date cluster."""
    facts={(fact['kind'],fact['period'],fact['field']):fact for fact in accepted['facts']}
    trace=[]
    def value(kind,period,field,decision):
        key=(kind,period.end_time.strftime('%Y%m%d'),field)
        fact=facts[key]
        trace.append({'kind':kind,'period':key[1],'field':field,'state':fact['state'],
            'available_at':fact.get('decision_available_at'),'eligible_observation_ids':fact['eligible_observation_ids']})
        if fact['state']!='PUBLIC_ORIGINAL_VALUE_RECONCILED':
            return None
        assert pd.Timestamp(fact['decision_available_at'])<=decision,key
        return Decimal(str(fact['value']))
    def quarter(kind,period,field,decision):
        current=value(kind,period,field,decision)
        if current is None or period.quarter==1:
            return current
        previous=value(kind,period-1,field,decision)
        return None if previous is None else current-previous
    def quality(period,decision):
        cash=quarter('cashflow',period,'n_cashflow_act',decision)
        profit=quarter('income',period,'n_income',decision)
        begin=value('balancesheet',period-1,'total_assets',decision)
        end=value('balancesheet',period,'total_assets',decision)
        assert all(v is not None for v in (cash,profit,begin,end))
        assert begin>0 and end>0
        return (cash-profit)/((begin+end)/2)
    events=defaultdict(set)
    for fact in accepted['facts']:
        if fact['period']>='20191231' and fact['state']=='PUBLIC_ORIGINAL_VALUE_RECONCILED':
            events[fact['decision_available_at']].add(fact['period'])
    records=[]
    with localcontext() as ctx:
        ctx.prec=40
        for number,(timestamp,periods) in enumerate(sorted(events.items()),1):
            decision=pd.Timestamp(timestamp)
            period=pd.Period(pd.Timestamp(max(periods)),freq='Q-DEC')
            trace=[]
            revenue=quarter('income',period,'revenue',decision)
            prior_revenue=quarter('income',period-4,'revenue',decision)
            cost=quarter('income',period,'oper_cost',decision)
            prior_cost=quarter('income',period-4,'oper_cost',decision)
            parent=quarter('income',period,'n_income_attr_p',decision)
            prior_parent=quarter('income',period-4,'n_income_attr_p',decision)
            assert all(v is not None for v in (revenue,prior_revenue,cost,prior_cost,parent,prior_parent))
            assert revenue>0 and prior_revenue>0,'GM comparison undefined; retain unavailable rather than invent growth'
            margin=(revenue-cost)/revenue
            old_margin=(prior_revenue-prior_cost)/prior_revenue
            q=quality(period,decision)
            prior_q=quality(period-4,decision)
            assets=value('balancesheet',period,'total_assets',decision)
            old_assets=value('balancesheet',period-4,'total_assets',decision)
            receiv=value('balancesheet',period,'accounts_receiv',decision)
            old_receiv=value('balancesheet',period-4,'accounts_receiv',decision)
            stock=value('balancesheet',period,'inventories',decision)
            old_stock=value('balancesheet',period-4,'inventories',decision)
            deducted=quarter('fina_indicator',period,'profit_dedt',decision)
            prior_deducted=quarter('fina_indicator',period-4,'profit_dedt',decision)
            unique={(item['kind'],item['period'],item['field']):item for item in trace}
            record={'event_id':f'FIN{number:02d}','decision_date':decision.strftime('%Y-%m-%d'),
                'decision_available_at':timestamp,'report_period':period.end_time.strftime('%Y%m%d'),
                'joint_report_periods':'|'.join(sorted(periods)),'joint_report_count':len(periods),
                'quarter_revenue':float(revenue),'quarter_prior_year_revenue':float(prior_revenue),
                'quarter_gross_margin':float(margin),'quarter_prior_year_gross_margin':float(old_margin),
                'revenue_yoy_difference':float(revenue-prior_revenue),'gross_margin_yoy_difference':float(margin-old_margin),
                'cash_support':float(q),'prior_year_cash_support':float(prior_q),'cash_support_yoy_difference':float(q-prior_q),
                'parent_profit_yoy_difference':float(parent-prior_parent),
                'deducted_profit_yoy_difference':float(deducted-prior_deducted) if deducted is not None and prior_deducted is not None else None,
                'receivables_asset_ratio_yoy_difference':float(receiv/assets-old_receiv/old_assets) if receiv is not None and old_receiv is not None else None,
                'inventory_asset_ratio_yoy_difference':float(stock/assets-old_stock/old_assets) if stock is not None and old_stock is not None else None,
                'F1':int(revenue>prior_revenue and margin>old_margin),'F2':int(q>prior_q),'PARENT':int(parent>prior_parent),
                'input_lineage':list(unique.values())}
            records.append(record)
    assert len(records)==25 and sum(record['joint_report_count'] for record in records)==27
    assert len({record['decision_date'] for record in records})==25
    return records


def main():
    def blocked(*args,**kwargs):
        raise RuntimeError('EX036 is offline-only')
    socket.socket.connect=blocked
    socket.create_connection=blocked
    assert not (EX/'others/financial_features.csv').exists()
    for rel,item in read(EX/'protocols/published_design.json').items():
        assert EvidenceRef.from_dict(item).resolve(ROOT).read_bytes()==(ROOT/rel).read_bytes()
    accepted=read(READY/'others/accepted_financial_inputs.json')
    ref=accepted['preparation_reference']
    reference=PreparedDataRef(UUID(ref['space_id']),UUID(ref['preparation_id']),ref['manifest_sha256'])
    context=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig(bindings={}))
    periods=tuple(pd.period_range('2018Q2','2026Q2',freq='Q-DEC').end_time.strftime('%Y-%m-%d'))
    frames={}
    checks=[]
    for kind in FinancialReportKind:
        request=DataRequest(Dataset.COMPANY_FINANCIAL_DISCLOSURES,'600722.SH','2018-07-01','2026-10-15',None,frequency='event',
            parameters=FinancialDisclosureParameters(kind,'2018-06-30','2026-06-30',
                **({'report_type':None} if kind is FinancialReportKind.FINANCIAL_INDICATOR else {}),expected_periods=periods))
        result=context.data.fetch(request,prepared=reference)
        assert result.ready,result.error
        frames[kind.value]=result.dataframe.set_index('RecordId',drop=False)
        checks.append({'check':'financial_pinned_fetch','kind':kind.value,'passed':True,'content_sha256':result.identity.content_sha256})
    for fact in accepted['facts']:
        if fact['state']=='PUBLIC_ORIGINAL_VALUE_RECONCILED':
            rows=frames[fact['kind']].loc[fact['eligible_observation_ids']]
            assert rows[fact['field']].notna().all()
            assert all(Decimal(str(value))==Decimal(str(fact['value'])) for value in rows[fact['field']])
            assert set(rows.end_date.astype(str))=={fact['period']}
    checks.append({'check':'296_admitted_field_values_bound_to_original_observations','passed':True})
    events=build_financial_features(accepted)
    write(EX/'others/financial_features_lineage.json',{'status':'PASS','events':events,
        'accepted_manifest_sha256':sha256((READY/'others/accepted_financial_inputs.json').read_bytes()).hexdigest(),
        'reference':ref,'checks':checks,'new_api_calls':0,'new_labels':0})
    frame=pd.DataFrame([{key:value for key,value in event.items() if key!='input_lineage'} for event in events])
    frame.to_csv(EX/'others/financial_features.csv',index=False,lineterminator='\n')
    print(json.dumps({'status':'PASS','events':len(events),'report_periods':27,
        'F1_positive':int(frame.F1.sum()),'F2_positive':int(frame.F2.sum()),'PARENT_positive':int(frame.PARENT.sum()),'new_api_calls':0}))


if __name__=='__main__':
    main()
