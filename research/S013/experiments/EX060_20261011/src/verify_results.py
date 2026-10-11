"""Focused actual-result transport, causality and independent IC checks."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, rankdata
from component_statistics import CONTROLS, COMPONENTS, HORIZONS

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-redesign-absolute'


def check():
    refs=json.loads((ROOT/'research/S013/experiments/EX060_20261011/protocols/result_references.json').read_text(encoding='utf-8'))
    from czsc_trader.research_tools.evidence import EvidenceRef
    for ref in refs.values():
        EvidenceRef.from_dict(ref).resolve(ROOT)
    feature=pd.read_csv(WORK/'features.csv',index_col='signal_date',float_precision='round_trip')
    feature.index=pd.to_datetime(feature.index)
    labels=pd.read_csv(WORK/'labels.csv',index_col='signal_date',float_precision='round_trip')
    labels.index=pd.to_datetime(labels.index)
    for col in labels.columns:
        if col.startswith('label_end_'):
            labels[col]=pd.to_datetime(labels[col])
    opportunity=pd.read_csv(WORK/'opportunity.csv',index_col='signal_date').iloc[:,0]
    assert opportunity.dtype==bool
    result=json.loads((WORK/'statistics.json').read_text(encoding='utf-8'))
    checks=[]
    for scope,panel in result['scopes'].items():
        selected=np.ones(len(feature),dtype=bool) if scope=='all' else opportunity.to_numpy()
        for label in HORIZONS:
            y=labels[label].to_numpy()
            for component in COMPONENTS:
                x=feature[component].to_numpy()
                expected=panel['labels'][label]['components'][component]
                good=selected & np.isfinite(x) & np.isfinite(y)
                np.testing.assert_allclose(spearmanr(x[good],y[good]).statistic,expected['spearman']['value'],rtol=0,atol=1e-14)
                controls=feature[list(CONTROLS)].to_numpy()
                good=good & np.isfinite(controls).all(axis=1)
                design=np.c_[np.ones(good.sum()),np.column_stack([rankdata(col) for col in controls[good].T])]
                residual=[]
                for values in (x[good],y[good]):
                    ranks=rankdata(values)
                    residual.append(ranks-design@np.linalg.lstsq(design,ranks,rcond=None)[0])
                np.testing.assert_allclose(np.corrcoef(*residual)[0,1],expected['partial_rank_ic']['value'],rtol=0,atol=1e-13)
                checks.append(scope+'::'+label+'::'+component+'::independent_ic')
            wf=panel['labels'][label]['walk_forward']
            for year,row in wf['yearly'].items():
                start=pd.Timestamp(row['first_actual_signaldate'])
                if row['latest_train_label_end'] is not None:
                    assert pd.Timestamp(row['latest_train_label_end'])<start
                checks.append(scope+'::'+label+'::'+year+'::strict_maturity')
            for model,records in wf['prediction_records'].items():
                if not records:
                    continue
                truth=np.array([r['target'] for r in records])
                prediction=np.array([r['prediction'] for r in records])
                metrics=wf['aggregate_models'][model]
                np.testing.assert_allclose(np.mean((truth-prediction)**2),metrics['mse'],rtol=0,atol=1e-14)
                checks.append(scope+'::'+label+'::'+model+'::prediction_mse')
    output={'status':'PASS','checks':checks,'check_count':len(checks),'source_and_selected_evidence_hashes':'PASS',
        'real_account_runs':0,'scope':'Independent Spearman and partial OLS on published CSV transport, actual annual maturity, retained prediction MSE; bootstrap not repeated after fixed successful run'}
    (WORK/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print({'focused_actual_checks':'PASS','count':len(checks)})


if __name__=='__main__':
    check()
