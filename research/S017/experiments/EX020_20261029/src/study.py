"""One frozen competition of entry mechanisms; diagnostic labels, no portfolios."""
# ruff: noqa: E402
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from hashlib import sha256
import gzip
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
from time import perf_counter

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import numpy as np
from czsc_trader.application import (RepositoryContext,create_research_context,publish_evidence,
                                    validate_experiment)
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,EvidenceRef,
    MaterialEvidenceWrite,ExperimentReportWrite,ExperimentOutcome,
    ExperimentValidationRequest,ExperimentValidationScope)
from signals import compute,PRIMARY

ROOT=Path(__file__).resolve().parents[5]
WORK=Path(__file__).resolve().parents[1]
OLD=ROOT/'research/S017/experiments/EX019_20261029'
REPOSITORY=RepositoryContext.discover(ROOT)
EXPERIMENT=ExperimentRef('S017',WORK.name)
HORIZONS=(3,13,26,65,130)
NAMES=tuple(PRIMARY)


def read(path):
    return json.loads(path.read_bytes())


def save(path,value):
    path.write_bytes(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False).encode('utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load_legacy():
    ref=EvidenceRef.from_dict(read(OLD/'others/pre_run_evidence.json')['study-source'])
    ref.resolve(ROOT)
    path=OLD/'src/study.py'
    if digest(path)!=ref.sha256:
        raise ValueError('Frozen EX019 implementation changed')
    spec=importlib.util.spec_from_file_location('ex019_frozen',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


legacy=load_legacy()


def context():
    scratch=ROOT/'.tmp/s017-entry-competition'
    scratch.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(scratch)
    return create_research_context(REPOSITORY,ResearchBatchRef('S017'),
        providers=legacy.ProviderConfig(bindings={}),execution_spec=legacy.SPEC,
        resources=legacy.ExecutionResources(max_workers=2,native_threads_per_worker=1,random_seed=17))


def scan_task(args):
    return legacy.scan_chunk(args)


def label_task(args):
    bars,constraints,indices,n=args
    rows=[]
    for i in indices:
        row=legacy.label(bars,constraints,i,n)
        at=bars.iloc[i+1].BarStart.tz_convert('America/New_York')
        row.update(date=str(at.date()),month=at.strftime('%Y-%m'),stratum=at.strftime('%Y-%m|%H:%M'),
            signal_at=bars.iloc[i].Date.isoformat(),entry_at=bars.iloc[i+1].BarStart.isoformat())
        rows.append(row)
    return n,rows


def match(control,selected):
    groups={}
    for r in control:
        if r['price_net_return'] is not None:
            groups.setdefault(r['stratum'],[]).append(r['price_net_return'])
    chosen=[r for r in selected if r['price_net_return'] is not None]
    counts=Counter(r['stratum'] for r in chosen)
    means={k:float(np.mean(v)) for k,v in groups.items()}
    if any(r['stratum'] not in groups for r in chosen):
        raise ValueError('Selected event lacks matched control support')
    result={'count':len(chosen),'control_mean':float(np.mean([means[r['stratum']] for r in chosen])) if chosen else None,
        'difference':legacy.stats([r['price_net_return']-means[r['stratum']] for r in chosen]),
        'control_support':{'unique_cells':len(counts),
            'singleton_target_events':sum(len(groups[r['stratum']])==1 for r in chosen),
            'all_target_cell_events':sum(len(groups[r['stratum']])==counts[r['stratum']] for r in chosen),
            'median_control_events_per_target':float(np.median([len(groups[r['stratum']]) for r in chosen])) if chosen else None,
            'minimum_control_events':min((len(groups[r['stratum']]) for r in chosen),default=None)}}
    return result


def concentration(rows):
    positive=[r for r in rows if r['price_net_return'] is not None and r['price_net_return']>0]
    total=sum(r['price_net_return'] for r in positive)
    yearly={y:sum(r['price_net_return'] for r in positive if r['date'].startswith(y))
            for y in map(str,range(2019,2026))}
    return {'positive_return_sum':total,'positive_events':len(positive),
        'largest_event_share':max((r['price_net_return'] for r in positive),default=0)/total if total else None,
        'largest_year_share':max(yearly.values())/total if total else None,
        'positive_sum_by_year':yearly,'scope':'Sum of independent event returns, not account PnL contribution.'}


def block_weights(day_count,replicates=1000,block=20,seed=17):
    if day_count<block:
        raise ValueError('Insufficient trading days for declared block length')
    rng=np.random.default_rng(seed)
    starts=rng.integers(0,day_count-block+1,size=(replicates,int(np.ceil(day_count/block))))
    offsets=np.arange(block)
    weights=np.zeros((replicates,day_count),dtype=np.int32)
    for j,values in enumerate(starts):
        indices=(values[:,None]+offsets[None,:]).ravel()[:day_count]
        weights[j]=np.bincount(indices,minlength=day_count)
    return weights,sha256(starts.astype('<i8').tobytes()).hexdigest()


def bootstrap(rows,selected,control,days,weights):
    day_index={d:i for i,d in enumerate(days)}
    cells={c:i for i,c in enumerate(sorted({r['stratum'] for r in rows}))}
    def arrays(pop):
        valid=[r for r in pop if r['price_net_return'] is not None]
        return (np.array([r['price_net_return'] for r in valid],dtype=float),
                np.array([day_index[r['date']] for r in valid],dtype=int),
                np.array([cells[r['stratum']] for r in valid],dtype=int))
    y,yd,yc=arrays(selected)
    x,xd,xc=arrays(control)
    means,differences=[],[]
    for w in weights:
        yw,xw=w[yd],w[xd]
        if not len(y) or yw.sum()==0:
            means.append(None)
            differences.append(None)
            continue
        denominator=np.bincount(xc,weights=xw,minlength=len(cells))
        numerator=np.bincount(xc,weights=xw*x,minlength=len(cells))
        baseline=np.divide(numerator,denominator,out=np.zeros_like(numerator),where=denominator>0)
        if np.any((yw>0)&(denominator[yc]==0)):
            raise ValueError('Bootstrap target lacks positive-weight matched controls')
        means.append(float(np.sum(yw*y)/yw.sum()))
        differences.append(float(np.sum(yw*(y-baseline[yc]))/yw.sum()))
    def interval(values):
        valid=[v for v in values if v is not None]
        return {'valid_replicates':len(valid),'empty_replicates':len(values)-len(valid),
                'interval_95':[float(x) for x in np.quantile(valid,[.025,.975])] if valid else None}
    return {'price_mean':interval(means),'matched_difference':interval(differences)}, {'price_mean':means,'matched_difference':differences}


def material(research,name,path):
    return publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),
        {'.json':'application/json','.gz':'application/gzip'}.get(path.suffix,'text/plain'),path.suffix[1:]))


def declared_sources():
    pairs=[('design',WORK/'protocols/design.md'),('authorization',WORK/'protocols/authorization.md')]
    pairs.extend((p.stem+'-source',p) for p in sorted((WORK/'src').glob('*.py')) if p.stem!='render')
    pairs.extend([('checks',WORK/'others/checks.json'),('legacy-label-source',OLD/'src/study.py'),
        ('original-pat-source',legacy.OLD/'src/strategy.py'),('prepared-reference',legacy.PREP),
        ('overview-reuse',WORK/'others/overview_reuse.json')])
    return pairs


def run():
    start=perf_counter()
    research=context()
    check=read(WORK/'others/checks.json')
    sources={p.name:digest(p) for p in (WORK/'src').glob('*.py') if p.stem not in ('render','lifecycle')}
    if check['status']!='PASS' or check['sources']!=sources:
        raise ValueError('Focused checks must bind exact current research sources')
    pre={name:material(research,name,path).to_dict() for name,path in declared_sources()}
    old_publication=read(OLD/'others/publication.json')
    prior_refs={k:EvidenceRef.from_dict(old_publication['materials'][k]) for k in ('events','analysis')}
    for ref in prior_refs.values():
        ref.resolve(ROOT)
    save(WORK/'others/pre_run_evidence.json',{'materials':pre,
        'previous':{k:r.to_dict() for k,r in prior_refs.items()}})
    print('PROTOCOL_SOURCES_PUBLISHED',flush=True)
    bars,constraints,identities=legacy.fetch(research)
    eligible=[i for i in range(260,len(bars)-1)
        if bars.iloc[i+1].BarStart.tz_convert('America/New_York').date()>=date(2019,1,2)]
    flags,ready,features=compute(bars)
    if not ready.iloc[eligible].all():
        raise ValueError('New definitions lack historical inputs at common eligible decisions')
    days=sorted({str(bars.iloc[i+1].BarStart.tz_convert('America/New_York').date()) for i in eligible})
    print('INPUTS_READY',len(eligible),'decisions',len(days),'sessions',flush=True)
    with ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
        parts=np.array_split(np.array(eligible),2)
        scanned=sorted(sum(pool.map(scan_task,[(bars,x.tolist()) for x in parts]),[]))
        old_signal={i for i,flag,_ in scanned if flag}
        flags['PAT']=[i in old_signal for i in range(len(bars))]
        signals={name:set(i for i in eligible if bool(flags[name].iloc[i])) for name in NAMES}
        print('SIGNAL_COUNTS',{k:len(v) for k,v in signals.items()},flush=True)
        labels={}
        for n,rows in pool.map(label_task,[(bars,constraints,eligible,n) for n in HORIZONS]):
            labels[n]=rows
            print('LABELS_COMPLETE',n,len(rows),flush=True)
    old_rows=json.loads(gzip.decompress(prior_refs['events'].resolve(ROOT).read_bytes()))
    old_by={(r['n'],r['i']):r for r in old_rows}
    recovered=0
    for n in (3,13,26):
        for row in labels[n]:
            previous=old_by[n,row['i']]
            if any(previous[k]!=v for k,v in row.items()) or previous['signal']!=(row['i'] in old_signal):
                raise ValueError('EX019 label or PAT signal did not reproduce')
            recovered+=1
    print('EX019_EXACT_ROWS_REPRODUCED',recovered,flush=True)
    weights,starts_hash=block_weights(len(days))
    summaries,draws={},{}
    all_rows=[]
    for n in HORIZONS:
        rows=labels[n]
        for row in rows:
            row['signals']=[name for name in NAMES if row['i'] in signals[name]]
        horizon={'all':legacy.summarize(rows),'signals':{}}
        for name in NAMES:
            chosen=[r for r in rows if name in r['signals']]
            sparse=legacy.nonoverlap(sorted(signals[name]),n)
            reduced=[r for r in chosen if r['i'] in sparse]
            value={'raw':legacy.summarize(chosen),'nonoverlap':legacy.summarize(reduced),
                'matched_raw':match(rows,chosen),'matched_nonoverlap':match(rows,reduced),
                'concentration_raw':concentration(chosen),'concentration_nonoverlap':concentration(reduced)}
            parent=[r for r in rows if 'A' in r['signals']]
            if name in ('AC','AV'):
                value['parent_matched_raw']=match(parent,chosen)
                value['parent_matched_nonoverlap']=match(parent,reduced)
            if n==PRIMARY[name]:
                value['years']={}
                value['months']={}
                for group in sorted({r['date'][:7] for r in rows}):
                    selected=[r for r in chosen if r['date'].startswith(group)]
                    value['months'][group]=legacy.summarize(selected)
                for year in map(str,range(2019,2026)):
                    selected=[r for r in chosen if r['date'].startswith(year)]
                    controls=[r for r in rows if r['date'].startswith(year)]
                    value['years'][year]={'raw':legacy.summarize(selected),'matched':match(controls,selected)}
                for mode,selected in [('raw',chosen),('nonoverlap',reduced)]:
                    key=f'{name}_{n}_{mode}'
                    value['bootstrap_'+mode],draws[key]=bootstrap(rows,selected,rows,days,weights)
                    if name in ('AC','AV'):
                        value['parent_bootstrap_'+mode],draws[key+'_parent']=bootstrap(rows,selected,parent,days,weights)
            horizon['signals'][name]=value
        summaries[str(n)]=horizon
        all_rows.extend(rows)
        print('SUMMARY_COMPLETE',n,flush=True)
    features_out=[]
    for i in eligible:
        features_out.append({'i':i,'signal_at':bars.iloc[i].Date.isoformat(),
            'signals':[n for n in NAMES if i in signals[n]],
            'facts':{k:float(v) for k,v in features.iloc[i].items()}})
    for name,value in [('events',all_rows),('signal_facts',features_out),('bootstrap_draws',draws)]:
        raw=json.dumps(value,ensure_ascii=False,default=str,allow_nan=False).encode('utf-8')
        (WORK/f'others/{name}.json.gz').write_bytes(gzip.compress(raw,mtime=0))
    save(WORK/'others/analysis.json',{'schema':'s017-entry-competition/v1','experiment':EXPERIMENT.to_dict(),
        'prepared':read(legacy.PREP)['reference'],'inputs':identities,'eligible':len(eligible),
        'signal_counts':{k:len(v) for k,v in signals.items()},'primary_horizons':PRIMARY,'horizons':summaries,
        'protocol_sha256':digest(WORK/'protocols/design.md'),'sources':sources,
        'artifacts':{n:digest(WORK/f'others/{n}.json.gz') for n in ('events','signal_facts','bootstrap_draws')},
        'legacy_reproduction':{'status':'PASS','exact_event_rows':recovered,'prior_refs':{k:r.to_dict() for k,r in prior_refs.items()}},
        'bootstrap':{'replicates':1000,'block_sessions':20,'seed':17,'sessions':len(days),
            'common_start_indices_sha256':starts_hash,'control_means_reestimated':True,
            'limits':'Marginal descriptive intervals, not multiplicity-adjusted; adaptive selection and longer dependence remain.'},
        'signal_overlap':{a:{b:len(signals[a]&signals[b]) for b in NAMES} for a in NAMES},
        'new_entry_expressions':5,'new_strategy_configurations':0,'new_account_replays':0,
        'signal_horizon_cells':30,'reserved_2026_used':False,'seconds':perf_counter()-start})
    print('ANALYSIS_COMPLETE',perf_counter()-start,flush=True)


def publish():
    research=context()
    pre=read(WORK/'others/pre_run_evidence.json')
    for name,path in declared_sources():
        reference=EvidenceRef.from_dict(pre['materials'][name])
        reference.resolve(ROOT)
        if digest(path)!=reference.sha256:
            raise ValueError('Pre-run material changed: '+name)
    analysis=read(WORK/'others/analysis.json')
    judgment=read(WORK/'others/judgment.json')
    checked=read(WORK/'others/result_validation.json')
    if (judgment['analysis_sha256']!=digest(WORK/'others/analysis.json') or checked['status']!='PASS'
            or checked['analysis_sha256']!=digest(WORK/'others/analysis.json')
            or checked['verification_source_sha256']!=digest(WORK/'src/verify.py')):
        raise ValueError('Judgment/verification must bind completed exact analysis')
    for name,expected in analysis['artifacts'].items():
        if expected!=digest(WORK/f'others/{name}.json.gz'):
            raise ValueError('Changed analysis artifact')
    extra={}
    for name,relative in [('analysis','others/analysis.json'),('events','others/events.json.gz'),
        ('signal-facts','others/signal_facts.json.gz'),('bootstrap-draws','others/bootstrap_draws.json.gz'),
        ('judgment','others/judgment.json'),('verification','others/result_validation.json'),('render-source','src/render.py')]:
        extra[name]=material(research,name,WORK/relative).to_dict()
    refs=tuple(EvidenceRef.from_dict(x) for x in [*pre['materials'].values(),*pre['previous'].values(),*extra.values()])
    ref=publish_evidence(research,ExperimentReportWrite(EXPERIMENT,digest(WORK/'report.md'),ExperimentOutcome.COMPLETED,refs))
    check=validate_experiment(REPOSITORY,ExperimentValidationRequest(EXPERIMENT,ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json',{'report':ref.to_dict(),'validation':check.to_dict(),'materials':extra,
        'new_account_replays':0,'new_entry_expressions':5,'panel_published':False})
    if check.status.value!='PASS':
        raise RuntimeError('Report publication failed validation')
    print('REPORT_PUBLICATION PASS',ref.to_dict(),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','publish'])
    run() if parser.parse_args().action=='run' else publish()
