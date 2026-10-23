"""P0: authenticate historical evidence and describe actual accounts, without re-fitting."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
import json
from datetime import date
from pathlib import Path
from hashlib import sha256
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, diagnose_accounts, publish_evidence
from czsc_trader.research_tools import (EvidenceRef, ExperimentRef, ResearchBatchRef, ExecutionResources,
    MaterialEvidenceWrite, AccountRunRef, AccountDiagnosisRequest, EvaluationIdentity,
    EvaluationWindow)
from strategy_manager import CandidateKey

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parent
EX = ExperimentRef('S015', HERE.name)
SOURCES = []

def read(path):
    return json.loads(path.read_bytes())

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def resolve(value):
    ref = EvidenceRef.from_dict(value)
    path = ref.resolve(ROOT)
    if ref.to_dict() not in SOURCES:
        SOURCES.append(ref.to_dict())
    return path

def material_from_report(ex, name, suffix):
    report = read(resolve(read(BASE/ex/'report_ref.json')['report']))
    matches = [x for x in report['evidence'] if x['name'] == name and x['evidence_id'].endswith('.'+suffix) and x['experiment']['experiment_id']==ex]
    assert len(matches) == 1, (ex, name, len(matches))
    return resolve(matches[0])

def material(ctx, path):
    return publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(),
        {'.py':'text/x-python', '.json':'application/json', '.csv':'text/csv', '.md':'text/markdown'}[path.suffix], path.suffix[1:]))

def main():
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(1,1,13))
    protocol = {'scope':'P0 historical diagnosis; no fits, new accounts, candidate search or data queries',
        'accounts':'EX042 six full-window accounts and C4307/C4507/C4607, with complete 159-configuration context',
        'method':'Public diagnose_accounts first. Unsupported remains unsupported. Independent ledger arithmetic is accounting description only.',
        'group':'First actual BUY decision r5 positive/negative/zero; do not filter based on outcomes',
        'bridge':'EX032 fixed four-fold predictions vs EX049 same-event rolling predictions; availability and schedules separately reported',
        'counterfactual_limit':'No subtraction of losing trades or simple multiplication by exposure is a strategy result'}
    save(HERE/'protocols/diagnosis.json', protocol)
    prerefs = [material(ctx, HERE/'protocols/diagnosis.json').to_dict(), material(ctx, Path(__file__)).to_dict()]
    oldpred = pd.read_csv(material_from_report('EX032_20261023', 'predictions', 'csv'))
    centers = pd.read_csv(material_from_report('EX047_20261023', 'all_centers', 'csv'))
    assert len(centers) == 159
    centers.to_csv(HERE/'others/historical_159_centers.csv', index=False)
    manifest = read(material_from_report('EX042_20261023','training_manifest','json'))
    schedule = {'EX032': oldpred.groupby(['lag','target','fold']).agg(n=('date','size'),first=('date','min'),last=('date','max')).reset_index().to_dict('records'),
        'EX042': {'first_position': min(x['position'] for x in manifest), 'releases': sorted(set(x['release'] for x in manifest)), 'models':len(manifest), 'minimum_training_n':min(x['train_n'] for x in manifest)},
        'interpretation':'Different features, update times, entry queues and account capital; raw historical difference is not an isolated component effect.'}
    save(HERE/'others/historical_schedules.json', schedule)
    diagnostics=[]; summaries=[]; cycle_rows=[]; selectedrefs=[]
    for exid, wanted in [('EX042_20261023',None),('EX043_20261023','C4307'),('EX045_20261023','C4507'),('EX046_20261023','C4607')]:
        results = read(material_from_report(exid,'results','json'))
        for row in results['rows']:
            cid = row['candidate_id']
            if wanted is not None and cid != wanted:
                continue
            evref = EvidenceRef.from_dict(row['evidence']); ev=read(resolve(row['evidence'])); selectedrefs.append(evref.to_dict())
            run = next(x for x in ev['runs'] if x['window_id']=='full')
            rawid=run['identity']; identity=EvaluationIdentity(CandidateKey(**rawid['candidate']), **{k:v for k,v in rawid.items() if k!='candidate'})
            result=diagnose_accounts(RepositoryContext.discover(ROOT), AccountDiagnosisRequest(AccountRunRef(evref,identity),None,EvaluationWindow('full',date(2025,1,2),date(2026,10,21))))
            diagnostics.append({'candidate':cid,'result':result.to_dict()})
            ledgers={k:pd.DataFrame(v['data']) for k,v in run['ledgers'].items()}
            daily, decisions, fills, orders = [ledgers[k] for k in ('account_daily','decisions','fills','orders')]
            daily['day']=daily.date.str[:10]; daily=daily.set_index('day')
            decisions=decisions.set_index('decision_id')
            fills['day']=fills.fill_time.str[:10]
            these=[]
            for cycle, group in fills.groupby('cycle_id',sort=False):
                buys=group[group.side=='BUY']; sells=group[group.side=='SELL']; first=buys.iloc[0]
                firstday=first['day']; decision=decisions.loc[first.decision_id]; remaining=int(buys.quantity.sum()-sells.quantity.sum())
                gross=float((sells.quantity*sells.price).sum()-(buys.quantity*buys.price).sum()+remaining*daily.close.iloc[-1])
                fees=float(group.fees.sum()); entry=float(sum(r.quantity*(daily.loc[firstday,'close']-r.price) for r in buys[buys.day==firstday].itertuples()))
                signalday=first.signal_date[:10]
                preentry=float(first.quantity*(first.price-daily.loc[signalday,'close'])) if signalday in daily.index else None
                record={'candidate':cid,'cycle_id':cycle,'first_entry_day':firstday,'signal_date':signalday,
                    'r5':float(decision.r5),'r5_sign':'up' if decision.r5>0 else 'down' if decision.r5<0 else 'zero',
                    'buy_fills':len(buys),'sell_fills':len(sells),'open_quantity':remaining,
                    'entry_day_gross_yuan':entry,'later_gross_yuan':gross-entry,'fees_yuan':fees,'net_yuan':gross-fees,
                    'signal_close_to_first_fill_price_change_yuan_not_account_pnl':preentry}
                these.append(record);cycle_rows.append(record)
            cycles=pd.DataFrame(these); net=float(daily.equity.iloc[-1])-100000
            residual=float(cycles.net_yuan.sum()-net); assert abs(residual)<1e-7,(cid,residual)
            ready=decisions.model_ready.astype(bool); allowed=decisions.permission.astype(bool)&ready
            actual_buy_decisions=set(fills.loc[fills.side=='BUY','decision_id'])
            same_day_buys=allowed.index.isin(actual_buy_decisions)
            summaries.append({'candidate':cid,'parameters':row['parameters'],'official_diagnosis':result.status.value,
                'net_yuan':net,'entry_day_gross_yuan':float(cycles.entry_day_gross_yuan.sum()),'later_gross_yuan':float(cycles.later_gross_yuan.sum()),
                'fees_yuan':float(cycles.fees_yuan.sum()),'residual':residual,'cycles':len(cycles),'multi_buy_cycles':int((cycles.buy_fills>1).sum()),
                'ready_decisions':int(ready.sum()),'allowed_decisions':int(allowed.sum()),'allowed_with_actual_buy':int((allowed&same_day_buys).sum()),
                'allowed_during_existing_intent':int((allowed & (decisions.intent_age>1)).sum()),'allowed_on_exit_intent':int((allowed & (decisions.intent_age==0)).sum()),
                'unfilled_buy_orders':int(((orders.side=='BUY') & (orders.status!='FILLED')).sum()),
                'r5_groups':cycles.groupby('r5_sign').agg(cycles=('cycle_id','size'),entry_gross=('entry_day_gross_yuan','sum'),later_gross=('later_gross_yuan','sum'),fees=('fees_yuan','sum'),net=('net_yuan','sum')).reset_index().to_dict('records'),
                'metrics':row['runs']})
            print(cid,result.status.value,'net',round(net,2),'reconciliation',residual,flush=True)
    pd.DataFrame(cycle_rows).to_csv(HERE/'others/cycle_accounting.csv',index=False)
    save(HERE/'others/public_diagnoses.json',diagnostics)
    save(HERE/'others/historical_results.json',{'accounts':summaries,'configurations':len(centers),'joint_pass':int(centers.joint_pass.sum()),'new_accounts':0,'fits':0,'sources':SOURCES,'account_sources':selectedrefs})
    refs={str(p.relative_to(HERE)).replace('\\','/'):material(ctx,p).to_dict() for p in sorted((HERE/'others').glob('*')) if p.suffix in ('.csv','.json') and p.name not in ('published_refs.json','historical_input_refs.json')}
    save(HERE/'others/historical_input_refs.json',{'inputs':SOURCES,'protocol_and_source':prerefs})
    refs['others/historical_input_refs.json']=material(ctx,HERE/'others/historical_input_refs.json').to_dict()
    save(HERE/'others/published_refs.json',{'materials':refs,'account_sources':selectedrefs,'protocol_and_source':prerefs})

if __name__=='__main__':
    main()
