"""Independent EX033 input/label/action audit; no fit, label creation or account replay."""
from pathlib import Path
from hashlib import sha256
from uuid import UUID
import json
import socket
import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
OUT=EX/'others'
CHECKS=0


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def check(condition, message):
    global CHECKS
    CHECKS += 1
    if not bool(condition):
        raise AssertionError(message)


def close(actual, expected, message):
    check(np.allclose(actual,expected,atol=1e-11,rtol=1e-10,equal_nan=True),message)


def blocked(*a,**kw):
    raise RuntimeError('EX033 independent audit is offline')


def main():
    socket.socket.connect=blocked
    socket.create_connection=blocked
    inputs=read(OUT/'inputs.json')
    events=pd.read_csv(OUT/'events.csv')
    check(sha256((OUT/'events.csv').read_bytes()).hexdigest()==inputs['events_sha256'],'events sha')
    for rel,digest in inputs['source_sha256'].items():
        check(sha256((ROOT/rel).read_bytes()).hexdigest()==digest,'source sha '+rel)
    diag_ref=EvidenceRef.from_dict(inputs['source_diagnostic'])
    diagnostic=json.loads(diag_ref.resolve(ROOT).read_bytes())
    check(sha256(diag_ref.resolve(ROOT).read_bytes()).hexdigest()==diag_ref.sha256,'label evidence')
    old=[r for r in diagnostic['episodes'] if r['window']=='ALL']
    early=[r for r in old if r['early_break']]
    paired=[r for r in early if r['matched_B_entry'] and r['both_closed']]
    unmatched=[r for r in early if not (r['matched_B_entry'] and r['both_closed'])]
    check((len(old),len(early),len(paired),len(unmatched))==(138,103,100,3),'population inventory')
    check(unmatched==inputs['unmatched_events'],'all exclusions retained')
    check(sum(not r['early_break'] for r in old)==35,'non early population')
    check(set(events.entry_date)=={r['entry_date'] for r in paired},'all pair identities')
    check(not events.entry_date.duplicated().any(),'entry identity unique')
    check(int(events.positive_mark.sum())==15 and int((~events.positive_mark).sum())==85,'85/15 split')
    episodes={r['entry_date']:r for r in paired}
    tables={}
    for variant,serialized in inputs['account_evidence'].items():
        ref=EvidenceRef.from_dict(serialized)
        raw=ref.resolve(ROOT).read_bytes()
        check(sha256(raw).hexdigest()==ref.sha256,'account evidence hash')
        payload=json.loads(raw)
        check(len(payload['runs'])==1,'one source run')
        table=pd.DataFrame(payload['runs'][0]['ledgers']['trades']['data'])
        table['entry_date']=pd.to_datetime(table.entry_date).dt.strftime('%Y-%m-%d')
        table['exit_date']=pd.to_datetime(table.exit_date).dt.strftime('%Y-%m-%d')
        tables[variant]=table.set_index('entry_date')
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig(bindings={}))
    frames={}
    for identity in inputs['native_identities']:
        bound=identity['reference']
        prepared=PreparedDataRef(UUID(bound['space_id']),UUID(bound['preparation_id']),bound['manifest_sha256'])
        dataset=Dataset(identity['dataset'])
        fetched=ctx.data.fetch(DataRequest(dataset,identity['symbol'],identity['start'],'2026-10-15','2026-10-15'),prepared=prepared)
        check(fetched.ready,'prepared data readiness')
        check(fetched.identity.content_sha256==identity['content_sha256'],'native source hash')
        data=fetched.dataframe.copy()
        data.index=pd.to_datetime(data.Date).dt.normalize()
        frames[identity['symbol']]=data.sort_index()
    check(set(frames)=={'600722.SH','000001.SH','000813.CSI'},'canonical symbols')
    stock=frames['600722.SH']
    cal=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(OUT/'calendar.csv').date))
    check(len(cal)==1642,'calendar length')
    check(cal.equals(stock.loc['2020-01-01':].index),'stock calendar')
    check(cal.equals(frames['000001.SH'].index) and cal.equals(frames['000813.CSI'].index),'exact SSE dates')
    floor=stock.Close.where(stock.index>=pd.Timestamp('2020-01-01')).shift(1).rolling(5,min_periods=5).min()
    for event in events.itertuples():
        source=episodes[event.entry_date]
        b=tables['support_entry_H10'].loc[event.entry_date]
        r=tables['support_exit_reserve_H10'].loc[event.entry_date]
        check(b.status==r.status=='CLOSED','closed legs')
        close(b.entry_price,r.entry_price,'same entry execution price')
        close([event.B_position_return,event.R_position_return],[b.net_return,r.net_return],'saved label ledger')
        close([event.B_position_return,event.R_position_return],[source['B_position_return'],source['R_position_return']],'saved label episode')
        check(event.B_exit_date==b.exit_date and event.R_exit_date==r.exit_date,'actual exit dates')
        e=pd.Timestamp(event.entry_date); d=pd.Timestamp(event.decision_date)
        ei=stock.index.get_loc(e); di=stock.index.get_loc(d)
        check(ei<=di<ei+9,'early trigger before H10 close deadline')
        check(stock.loc[d,'Close']<floor.loc[d],'actual support break')
        check(not (stock.Close.iloc[ei:di]<floor.iloc[ei:di]).any(),'first support break')
        check(event.decision_date==source['decision_date'],'decision identity')
        check(event.remaining_to_H10_sessions==10-(di-ei),'remaining to scheduled E+10 execution session')
        check(event.decision_year==d.year and event.entry_year==e.year,'year semantics')
        check(d<pd.Timestamp(event.R_exit_date) and d<pd.Timestamp(event.B_exit_date),'actions available before execution')
        prior=stock.index[di-1]
        check(event.feature_previous_date==str(prior.date()),'previous session exact')
        values=[frames[symbol].loc[d,'Close']/frames[symbol].loc[prior,'Close']-1 for symbol in ['600722.SH','000001.SH','000813.CSI']]
        close([event.stock_return,event.market_return,event.sector_return],values,'returns exact date')
        close(event.amplitude,(stock.loc[d,'High']-stock.loc[d,'Low'])/stock.loc[d,'Close'],'amplitude')
        p=stock.loc[d,'Close']/diagnostic['scale_anchor']/(float(r.entry_price)*1.001)-1
        close(event.close_net_of_buy_fee_return,p,'known floating PNL including buy fee')
        c=bool(values[1]<0 and values[2]<0); resilient=bool(values[0]>=values[2])
        check(event.common_decline==c and event.relative_resilient==resilient,'zero threshold C and R')
        check(event.hold_P==(p<=0) and event.hold_candidate==(p<=0 and c and resilient),'single authorized action')
        close(event.action_delta,event.B_position_return-event.R_position_return,'action label sign')
    delta=events.action_delta.to_numpy()
    base=events.R_position_return.to_numpy()
    h=events.hold_candidate.to_numpy(dtype=bool); p=events.hold_P.to_numpy(dtype=bool)
    actions={'R':base,'B':base+delta,'P':base+delta*p,'candidate':base+delta*h}
    summary={name:{'n':len(v),'mean':float(v.mean()),'sum':float(v.sum())} for name,v in actions.items()}
    close(actions['B'],events.B_position_return,'all hold identity')
    close(actions['candidate']-actions['R'],delta*h,'candidate minus R identity')
    close(actions['candidate']-actions['P'],delta*(h.astype(int)-p.astype(int)),'candidate minus P identity')
    group=events.loc[events.hold_P & events.common_decline]
    strata=[]
    for key,g in group.groupby(['decision_year','remaining_to_H10_sessions']):
        a=g[g.relative_resilient]; b=g[~g.relative_resilient]
        if len(a) and len(b):
            strata.append({'year':int(key[0]),'remaining':int(key[1]),'n_resilient':len(a),'n_weak':len(b),'weight':min(len(a),len(b)),'contrast':float(a.action_delta.mean()-b.action_delta.mean())})
    totalweight=sum(s['weight'] for s in strata)
    weighted=None if not totalweight else sum(s['weight']*s['contrast'] for s in strata)/totalweight
    # Inclusive transitive interval clusters; touching dates are one cluster.
    assignments={}; cluster=-1; right=None
    for row in events.sort_values('entry_date').itertuples():
        start=pd.Timestamp(row.entry_date); end=max(pd.Timestamp(row.B_exit_date),pd.Timestamp(row.R_exit_date))
        if right is None or start>right:
            cluster+=1;right=end
        else:
            right=max(right,end)
        assignments[int(row.event_id)]=cluster
    result={'status':'PASS','checks':CHECKS,'source':'Independent native bound data and immutable EX023 labels; no analysis-module imports',
            'population':{'old_cycles':138,'early':103,'matched':100,'nonpositive':85,'positive':15},
            'action_means':summary,'candidate_hold_n':int(h.sum()),'common_decline_nonpositive_n':len(group),
            'common_support_strata':strata,'common_support_weight':totalweight,'common_support_contrast':weighted,
            'interval_clusters':cluster+1,'cluster_assignments':assignments,
            'new_data_calls':0,'new_fits':0,'new_labels':0,'new_accounts':0,
            'remaining_definition':'E+10 planned execution session minus decision index, not actual delayed B execution',
            'limitations':['Conditional use of previously seen same-entry labels; neither a new account nor independent unseen validation.'],
            'audited_hashes':{p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in [EX/'src/prepare.py',EX/'protocols/design.json',OUT/'inputs.json',OUT/'events.csv',Path(__file__)]}}
    path=OUT/'independent_audit.json'
    with path.open('x',encoding='utf-8',newline='\n') as f:
        f.write(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':'PASS','checks':CHECKS,'candidate_hold_n':int(h.sum()),'common_support_weight':totalweight,'clusters':cluster+1}))


if __name__=='__main__':
    main()
