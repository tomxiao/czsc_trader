"""Authenticate all ten rounds and independently recompute every center gate."""
from hashlib import sha256
import importlib.util
import io
import zipfile

import numpy as np
import pandas as pd
from suite import ROOT,HOME,read,save,EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence


def main():
    base_ref=EvidenceRef.from_dict(read(ROOT/'research/S015/experiments/EX013_20261023/protocols/fixed_set.json')['archive_reuse']['S011-v1'])
    with zipfile.ZipFile(base_ref.resolve(ROOT)) as z:
        baseline=pd.read_csv(io.BytesIO(z.read('account_daily.csv')),float_precision='round_trip')
    baseline_dates=baseline.date.astype(str).str[:10].tolist()
    all_rows,rounds,contents,paths,derived_sources=[],[],set(),{},[]
    representatives={}
    for number in range(1,11):
        here=ROOT/f'research/S015/experiments/EX{15+number:03d}_20261023'
        publication=read(here/'others/publication_validation.json')
        report_ref=EvidenceRef.from_dict(publication['report'])
        snapshot=read(report_ref.resolve(ROOT))
        assert snapshot['report_sha256']==sha256((here/'report.md').read_bytes()).hexdigest()
        result_ref=next(EvidenceRef.from_dict(x) for x in snapshot['evidence'] if x['name']=='round_results')
        result=read(result_ref.resolve(ROOT))
        assert result==read(here/'others/results.json')
        derived_sources += [report_ref.to_dict(),result_ref.to_dict()]
        round_info={'round':number,'experiment':here.name,'configurations':len(result['rows']),
            'default434_center_pass':0,'return415_pass':0,'dd415_pass':0,'joint_center_pass':0,
            'report':report_ref.to_dict(),'results':result_ref.to_dict()}
        for row in result['rows']:
            ref=EvidenceRef.from_dict(row['evidence'])
            payload=read(ref.resolve(ROOT))
            validate_evaluation_evidence(payload)
            q=payload['request_identity']
            assert q['initial_cash']==100000 and q['symbol']=='159326.SZ' and q['data_cutoff']=='2026-10-21'
            assert q['costs']==[{'measurement_tier':'FORMAL','one_way_cost':.001,'scenario_id':'standard'}]
            assert q['windows']==[{'end':'2026-10-21','start':'2025-01-02','window_id':'full'},
                                  {'end':'2026-10-21','start':'2025-02-06','window_id':'s011_common'}]
            contents.add(q['content_sha256'])
            computed={}
            for run in payload['runs']:
                sid=run['window_id']
                tables={k:pd.DataFrame(t['data']) for k,t in run['ledgers'].items()}
                a,f,t=tables['account_daily'],tables['fills'],tables['trades']
                n=434 if sid=='full' else 415
                assert len(a)==n and a.cash_before.iloc[0]==100000 and a.quantity_before.iloc[0]==0
                eq=np.r_[100000.,a.equity.to_numpy(float)]
                ret=float(eq[-1]/100000-1)
                dd=float((1-eq/np.maximum.accumulate(eq)).max())
                cagr=float((eq[-1]/100000)**(252/n)-1)
                np.testing.assert_allclose(f.fees,f.quantity*f.price*.001,atol=1e-8,rtol=1e-12)
                for name,value in [('net_return',ret),('dd',dd),('cagr',cagr)]:
                    assert abs(value-row['runs'][sid][name])<1e-14
                assert abs(cagr-run['observation']['net_cagr'])<1e-12
                assert abs(dd-abs(run['observation']['max_drawdown']))<1e-12
                dates=pd.DatetimeIndex(pd.to_datetime(a.date)).normalize()
                exits=pd.to_datetime(t.loc[t.status.eq('CLOSED'),'exit_date']).dt.normalize()
                roll=exits.value_counts().reindex(dates,fill_value=0).rolling(60).sum().dropna()
                assert len(roll)==n-59
                good=int((roll>=3).sum())
                assert good==row['runs'][sid]['frequency_good']
                assert float(roll.median())==row['runs'][sid]['frequency_median']
                if sid=='full':
                    gate=all([cagr>=1.5*row['runs'][sid]['benchmark_cagr'],
                        dd<=.8*row['runs'][sid]['benchmark_dd'],dd<=.25,float(roll.median())>=6,good*10>=9*375])
                    assert gate==row['runs'][sid]['center_pass']
                    computed['default434_pass']=gate
                else:
                    assert a.date.astype(str).str[:10].tolist()==baseline_dates
                    np.testing.assert_allclose(a.close.to_numpy(float),baseline.close.to_numpy(float),atol=0,rtol=0)
                    computed.update(net_return=ret,dd=dd,return_pass=ret>.9158029150000013,dd_pass=dd<.07248663749114126)
                    fingerprint=sha256(np.asarray(a.equity,dtype='<f8').tobytes()).hexdigest()
                    paths.setdefault(fingerprint,[]).append({'round':number,'candidate_id':row['candidate_id']})
                    representatives[(number,row['candidate_id'])]=tables
            joint=computed['default434_pass'] and computed['return_pass'] and computed['dd_pass']
            assert joint==row['both_center_pass']
            all_rows.append({'round':number,'experiment':here.name,'candidate_id':row['candidate_id'],
                'parameters':row['parameters'],'content_sha256':q['content_sha256'],**computed,'joint_center_pass':joint,
                'evidence':ref.to_dict()})
            for name,k in [('default434_center_pass','default434_pass'),('return415_pass','return_pass'),('dd415_pass','dd_pass')]:
                round_info[name]+=int(computed[k])
            round_info['joint_center_pass']+=int(joint)
        rounds.append(round_info)
    total={'configurations_evaluated':len(all_rows),'unique_content_hashes':len(contents),
        'unique415_equity_paths':len(paths),'account_scenarios':2*len(all_rows),
        'technical_precheck_scenarios':2,'technical_pre_summary_failure_scenarios':2,
        'actual_computed_strategy_account_scenarios':2*len(all_rows)+4,
        'rounds_completed':10,'remaining_rounds':0,
        'default434_center_pass':sum(r['default434_pass'] for r in all_rows),
        'return415_pass':sum(r['return_pass'] for r in all_rows),'dd415_pass':sum(r['dd_pass'] for r in all_rows),
        'joint_center_pass':sum(r['joint_center_pass'] for r in all_rows),'qualified_strategies':0,
        'perturbation_and_stress_scenarios':0,
        'validation_reason':'No candidate passed both center windows; no incomplete candidate promoted to32point/fee acceptance.'}
    assert total['joint_center_pass']==0,'Qualified centers require original stage4 validation before closeout'
    eligible=[r for r in all_rows if r['default434_pass'] and r['return_pass']]
    passing_dd=[r for r in all_rows if r['dd_pass']]
    selected={'highest_return':max(all_rows,key=lambda r:r['net_return']),
        'lowest_dd_among_return_and434_pass':min(eligible,key=lambda r:r['dd']),
        'lowest_dd':min(all_rows,key=lambda r:r['dd']),
        'highest_return_among_dd_pass':max(passing_dd,key=lambda r:r['net_return'])}
    # Existing RSCH actual-account arithmetic, separately identified from public cycle diagnosis.
    origin=ROOT/'research/S015/experiments/EX014_20261023/src/diagnose.py'
    declared=read(origin.parents[1]/'others/protocol_refs.json')
    source_ref=next(EvidenceRef.from_dict(x) for x in declared if x['name']=='diagnosis_source')
    assert sha256(origin.read_bytes()).hexdigest()==source_ref.sha256
    spec=importlib.util.spec_from_file_location('retained_account_arithmetic',origin)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    decompositions={}
    for name,row in selected.items():
        tables=representatives[(row['round'],row['candidate_id'])]
        facts,_=module.breakdown(tables)
        decompositions[name]={'candidate_id':row['candidate_id'],'round':row['round'],**facts}
    register_before=read(ROOT/'research/S015/experiments/EX014_20261023/others/verification.json')['candidate_registration_hashes']
    register_after={p.name:sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research/registrations/S015/candidates').glob('*.json')}
    assert register_before==register_after
    value={'status':'PASS_AUTHENTICATION_AND_INDEPENDENT_CENTER_GATES','totals':total,'rounds':rounds,
        'representatives':selected,'representative_accounting':decompositions,'rows':all_rows,
        'sources':derived_sources,'baseline':base_ref.to_dict(),'account_arithmetic_source':source_ref.to_dict(),
        'candidate_registrations_unchanged':len(register_before),
        'limits':['Exact repeated and correlated paths are not independent validation.',
            'No original eligibility/ASSESSMENT overwritten; stages3/4 distinct.',
            'Loss accounting is RSCH arithmetic; public single-cycle API remains unsupported for scaling.']}
    save(HOME/'others/ten_round_audit.json',value)
    pd.DataFrame([{k:v for k,v in r.items() if k not in ('evidence','parameters')} for r in all_rows]).to_csv(HOME/'others/ten_round_results.csv',index=False,lineterminator='\n')
    print(total,flush=True)


if __name__=='__main__':
    main()
