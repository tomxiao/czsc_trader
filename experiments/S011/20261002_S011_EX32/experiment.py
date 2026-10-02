"""Current managed rerun of the fixed S011 component role tests."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from dataflows import DataRequest, Dataset
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentProtocol, ExperimentStage, ExperimentDependency, ExperimentCapabilities,
    ExperimentPrecheckResult, ExperimentPreflightCheck, ExperimentPreflightStatus,
    ExperimentResult, ExperimentOutcome,
)
from component_methods import indexed, calculate, labels, audit, synthetic, synthetic_audit, REVIEW

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
ID=ROOT.name
REQUESTS=(
    ('etf',Dataset.ETF_OHLCV,'159326.SZ','2024-09-09','daily'),
    ('bars',Dataset.ETF_OHLCV,'159326.SZ','2024-12-26','30m'),
    ('large',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000300.SH','2024-06-01','daily'),
    ('small',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000905.SH','2024-06-01','daily'),
    ('spx',Dataset.GLOBAL_INDEX_DAILY,'SPX','2024-06-01','daily'),
)

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, experiment_id=ID, strategy_id='S011', mode=ExperimentMode.FORMAL,
            data_scope=ExperimentDataScope.DEVELOPMENT, development_cutoff=date(2026,9,28),
            random_seed=2026092911, subjects=('159326.SZ',),
            research_question='Do the fixed four component roles retain their recorded evidence under current APIs?',
            hypothesis='Nine fixed definitions and seven labels reproduce the original role statistics.',
            falsification_conditions=('Fresh managed data changes role evidence beyond tolerance',),
            allowed_datasets=tuple(dict.fromkeys(x[1].value for x in REQUESTS)),
            dependencies=tuple(ExperimentDependency(k,v) for k,v in [('numpy',np.__version__),('pandas',pd.__version__),('scipy',scipy.__version__)]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(ExperimentStage.FEATURE_DISCOVERY,
                ('Role information is distinct from tradable profitability',),
                ('Managed observations to fixed definitions and future path labels',),
                ('Reproduce the fixed component role evidence',),
                ('Rank, partial rank, forecast error and adverse evidence',),
                ('No new search; historical broad screening attached with original limits',), ()))

    def synthetic_precheck(self):
        synthetic()
        synthetic_audit()
        return ExperimentPrecheckResult((ExperimentPreflightCheck('ROLE_COMPUTATION',ExperimentPreflightStatus.PASS,
            'Causal prefix, adjustment invariance, strict prior alignment and complete numeric audit exercised'),),
            ExperimentResult(ExperimentOutcome.PASS,{'synthetic_only':True},{}))

    def execute(self, context):
        historical=json.loads((ROOT/'historical_sources.json').read_text(encoding='utf-8'))
        for path,digest in historical.items():
            assert sha256((REPO/path).read_bytes()).hexdigest()==digest,path
        frames={}; artifacts=[]; identities={}
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,encoding='utf-8',lineterminator='\n',
                compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)
            artifacts.append(context.workspace.register_artifact(name,'component-evidence'))
        for name,dataset,symbol,start,frequency in REQUESTS:
            result=context.data.fetch(DataRequest(dataset,symbol,start,'2026-09-28',None,frequency))
            assert result.ready and result.identity is not None, (name,result.status)
            frames[name]=result.dataframe
            identities[name]={'content_sha256':result.identity.content_sha256,'metadata':dict(result.identity.metadata)}
            save('source_'+name+'.csv.gz',result.dataframe)
        assert identities['etf']['metadata'].get('adjustment')=='hfq'
        assert identities['bars']['metadata'].get('adjustment')=='hfq'
        assert identities['spx']['metadata'].get('unit')=='decimal_return'
        for name in ('etf','bars'):
            assert pd.to_datetime(frames[name].AvailableDate).dt.strftime('%H:%M:%S').eq('17:00:00').all()
        etf=indexed(frames['etf'])
        assert len(etf)==497 and len(frames['bars'])==3408
        x=calculate(etf,frames['bars'],indexed(frames['large']),indexed(frames['small']),indexed(frames['spx']))
        x['daily__return_5']=etf.Close.pct_change(5,fill_method=None)
        x['daily__vol_20']=etf.Close.pct_change(fill_method=None).rolling(20).std()
        y=labels(etf)
        prior=REPO/'experiments/S011/20260929_S011_EX10/artifacts'
        old_x=indexed(pd.read_csv(prior/'factor_matrix.csv.gz'))
        old_y=indexed(pd.read_csv(prior/'future_labels.csv.gz'))
        checks=[]
        for name in x:
            np.testing.assert_allclose(x[name],old_x[name],rtol=1e-9,atol=1e-12,equal_nan=True)
            checks.append({'Factor':name,'ComparedRows':len(x),'FiniteN':int(x[name].notna().sum()),'MaxAbsError':float((x[name]-old_x[name]).abs().max())})
        np.testing.assert_allclose(y,old_y,rtol=1e-9,atol=1e-12,equal_nan=True)
        ledger=pd.read_csv(prior/'information_ledger.csv')
        scores,folds,months=audit(x,y,ledger)
        for name,frame in [('role_evidence.csv',scores),('role_folds.csv',folds),('leave_month.csv',months)]:
            old=pd.read_csv(REPO/'experiments/S011/20260929_S011_EX12/artifacts'/name)
            pd.testing.assert_frame_equal(frame,old,check_dtype=False,rtol=1e-8,atol=1e-10)
            save(name,frame)
        save('definition_checks.csv',pd.DataFrame(checks))
        save('review_component_values.csv.gz',x.reset_index(names='Date'))
        save('future_labels.csv.gz',y.reset_index(names='Date'))
        summary={'definition_count':len(REVIEW),'role_tests':len(scores),'folds':len(folds),'leave_month_paths':len(months),
            'data_identities':identities,'comparison':'PASS','independent_evidence':False,
            'historical_screening_rerun':False,'historical_source_count':len(historical)}
        context.workspace.path('summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        artifacts.append(context.workspace.register_artifact('summary.json','component-summary'))
        return ExperimentResult(ExperimentOutcome.PASS,{'role_tests':len(scores),'folds':len(folds),'comparison':'PASS'},
            {'development_only':True,'historical_screening_rerun':False},tuple(artifacts))
