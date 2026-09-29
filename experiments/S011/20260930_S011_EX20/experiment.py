"""Reconstruct EX19 optimizer trace from sealed full-account results; no new search."""
from pathlib import Path
from datetime import date
import importlib.util
from hashlib import sha256
import json
import numpy as np
import pandas as pd
import optuna
from dataflows import Dataset
from research_experiment import (ResearchExperiment,ExperimentDefinition,ExperimentMode,
    ExperimentStage,ExperimentProtocol,ExperimentDependency,ExperimentCapabilities,
    ExperimentCapability,ExperimentResult,ExperimentOutcome)
from czsc_trader.experiment_archive import validate_experiment_archive

ID='20260930_S011_EX20';SEED=2026093020;BUDGET=1;CUTOFF=date(2026,9,28)
PREDECESSORS={'20260930_S011_EX16':'8df1748c63ac7ef1601203a161968351214ddf10b4fa7e83673946bf5924622e'}
FAILED_SOURCE_MANIFEST='07cb6e1f8eaff47a364810cf1255b61aaa6b5b3c4df830b5ff0bb70c0d4f95b2'
COMPLETED=368
ROOT=Path(__file__).resolve().parent


def completed_record(study,number,parameters):
    # Select the completed trial by number, never the end of a pre-enqueued queue.
    frozen=study.trials[number]
    if frozen.state.name!='COMPLETE':raise ValueError('trial not complete')
    value={'number':number,'state':frozen.state.name,'parameters':parameters,'sampler_parameters':frozen.params,
        'values':frozen.values,'user_attrs':frozen.user_attrs,'system_attrs':frozen.system_attrs,
        'distributions':{k:optuna.distributions.distribution_to_json(v) for k,v in frozen.distributions.items()}}
    return json.loads(json.dumps(value))


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.DISCOVERY,
            research_question='Can all sealed EX19 adaptive proposals and gates be reconstructed despite the first 11 export defects?',
            hypothesis='The defect affects queued-state export only; actual proposals, complete accounts and eligibility are reproducible.',
            falsification_conditions=('Any proposal differs','Any full-account metric or hard gate differs',
                                     'Discrepancy extends beyond the first 11 exported states'),
            development_cutoff=CUTOFF,random_seed=SEED,
            allowed_datasets=(Dataset.ETF_UNADJUSTED_DAILY.value,),subjects=('159326.SZ',),
            dependencies=tuple(ExperimentDependency(n,v) for n,v in
                (('numpy',np.__version__),('pandas',pd.__version__),('optuna',optuna.__version__))),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(stage=ExperimentStage.PROTOTYPE,
                first_principles=('Trace exports must describe the completed trial and preserve causal adaptive history',),
                information_paths=('Sealed account -> checked metrics -> seeded sampler replay -> corrected supplemental trace',),
                stage_objectives=('Audit optimizer identity and original qualification without new strategy evaluation',),
                observation_metrics=('Proposal equality','Ledger metrics','Export discrepancy scope','Pareto equality'),
                methodology=('No new accounts or parameters; all 368 completed sealed trials retained','Original defective exports and failed T368 immutable'),
                predecessor_experiment_ids=tuple(PREDECESSORS)))

    def synthetic_precheck(self):
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study=optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=SEED),directions=['maximize','maximize'])
        study.enqueue_trial({'x':0.});study.enqueue_trial({'x':1.})
        trial=study.ask();x=trial.suggest_float('x',0.,1.);study.tell(trial,values=[x,-x])
        record=completed_record(study,trial.number,{'x':x})
        assert record['state']=='COMPLETE' and record['sampler_parameters']=={'x':0.}
        assert study.trials[-1].state.name=='WAITING'
        try:completed_record(study,1,{'x':1.})
        except ValueError:pass
        else:raise AssertionError('queued trial accepted')
        bd=-.31;assert np.nextafter(bd,np.inf)>bd

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        for ex,sha in PREDECESSORS.items():
            validate_experiment_archive(ROOT.parent/ex)
            assert context.predecessors[ex].receipt_sha256==sha
        source=ROOT.parent/'20260930_S011_EX19';p=source/'artifacts'
        validate_experiment_archive(source)
        assert sha256((source/'experiment_manifest.json').read_bytes()).hexdigest()==FAILED_SOURCE_MANIFEST
        spec=importlib.util.spec_from_file_location('sealed_ex19_sampler',source/'experiment.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        table=pd.DataFrame([json.loads((p/f'trials/T{i:03}/metrics.json').read_text()) for i in range(COMPLETED)])
        assert len(table)==COMPLETED and table.trial.tolist()==list(range(COMPLETED))
        bh=pd.read_csv(ROOT.parent/'20260930_S011_EX16/artifacts/benchmark_account_daily.csv.gz')
        be=bh.equity;bc=float((be.iloc[-1]/1e6)**(252/len(be))-1);bd=float((be/be.cummax().clip(lower=1e6)-1).min())
        study=m.make_study()
        for point in m.seed_configurations():study.enqueue_trial(point)
        corrected=[];discrepancies=[];qualified=[]
        for row in table.itertuples():
            path=p/f'trials/T{row.trial:03}'
            metrics=json.loads((path/'metrics.json').read_text())
            payload=json.loads((path/'payload.json').read_text())
            original=json.loads((path/'optuna_trial.json').read_text())
            account=pd.read_csv(path/'account_daily.csv.gz');trades=pd.read_csv(path/'trades.csv.gz')
            assert account.date.equals(bh.date)
            eq=account.equity;n=len(eq);c=float((eq.iloc[-1]/1e6)**(252/n)-1)
            d=float((eq/eq.cummax().clip(lower=1e6)-1).min())
            count=int(trades.status.eq('CLOSED').sum());freq=60*count/n
            assert np.allclose([c,d,freq],[metrics['cagr'],metrics['drawdown'],metrics['frequency']],rtol=0,atol=1e-12)
            assert np.allclose([row.cagr,row.drawdown,row.frequency,row.buyhold_cagr,row.buyhold_drawdown],[c,d,freq,bc,bd],rtol=0,atol=1e-12)
            eligible=c>=1.5*bc and (bc>0 or(c>0 and c>bc)) and d>bd and 4<=freq<=6
            assert eligible==metrics['qualified']==row.qualified
            if eligible:qualified.append(row.trial)
            trial=study.ask();params=m.suggest(trial)
            assert params==payload['parameters']==original['parameters']
            assert original['number']==trial.number==row.trial
            constraints=[float(1.5*bc-metrics['cagr']),float(np.nextafter(bd,np.inf)-metrics['drawdown']),
                         float(4-metrics['frequency']),float(metrics['frequency']-6)]
            trial.set_user_attr('constraints',constraints)
            study.tell(trial,values=[metrics['cagr'],metrics['drawdown']])
            record=completed_record(study,trial.number,params)
            if original!=record:discrepancies.append(trial.number)
            corrected.append(record)
        assert discrepancies==list(range(11)),discrepancies
        pareto=m.frontier(table)
        pending=study.ask();pending_parameters=m.suggest(pending)
        assert pending.number==COMPLETED
        assert pending_parameters==json.loads((p/f'trials/T{COMPLETED:03}/payload.json').read_text())['parameters']
        failure=json.loads((p/f'trials/T{COMPLETED:03}/failure.json').read_text())
        assert failure['state']=='FAIL' and failure['parameters']==pending_parameters
        summary={'decision':'TRACE_RECONSTRUCTED_AND_ACCOUNT_GATES_CONFIRMED','source_manifest_sha256':FAILED_SOURCE_MANIFEST,
            'source_status':'TECHNICAL_FAILURE','source_receipt':None,
            'proposals_reproduced':COMPLETED,'pending_proposal_reproduced':COMPLETED,'evaluated':0,'qualified':len(qualified),'qualified_trials':qualified,
            'export_discrepancy_trials':discrepancies,'pareto_trials':pareto,'new_strategy_accounts':0,
            'development_only':True,'stage_four_complete':False}
        artifacts=[]
        table.to_csv(context.workspace.path('trials.csv'),index=False,lineterminator='\n')
        artifacts.append(context.workspace.register_artifact('trials.csv','S011-EX20-account-index'))
        for name,value in [('corrected_trials.json',corrected),('summary.json',summary),('pending_parameters.json',pending_parameters)]:
            context.workspace.path(name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX20-trace-audit'))
        return ExperimentResult(outcome=ExperimentOutcome.PASS,facts=summary,diagnostics={},artifacts=tuple(artifacts))
