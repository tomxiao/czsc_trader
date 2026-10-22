"""Independent arithmetic and augmented least-squares replication, not new research."""
from hashlib import sha256

from entry_day_study import ROOT, HERE, COLS, FOLDS, read, save, sources
import numpy as np
import pandas as pd


def main():
    refs = sources()
    x = pd.read_csv(refs['features'].resolve(ROOT))
    labels = pd.read_csv(HERE/'others/entry_labels.csv')
    g = pd.read_csv(HERE/'others/forward_predictions.csv')
    result = read(HERE/'others/results.json')
    filled = labels[labels.status.eq('FILLED')]
    np.testing.assert_allclose(filled.gross, filled.quantity*(filled.close-filled.buy_price)/100000, atol=1e-14, rtol=0)
    np.testing.assert_allclose(filled.buy_fee, filled.quantity*filled.buy_price*.001/100000, atol=1e-14, rtol=0)
    np.testing.assert_allclose(filled.net_entry, filled.gross-filled.buy_fee, atol=1e-14, rtol=0)
    assert labels.loc[~labels.status.eq('FILLED'), ['gross','net_entry']].isna().all().all()
    lab = labels.set_index('date').reindex(x.date)
    valid = lab.status.eq('FILLED').to_numpy() & np.isfinite(x[COLS['AllDaily']].to_numpy()).all(1)
    y, positions = lab.gross.to_numpy(), np.arange(len(x))
    maximum = 0.
    for fold,(left,right) in enumerate(FOLDS):
        start,stop = left+75,right+75
        train = np.flatnonzero(valid & (positions<start) & (lab.label_end_position.to_numpy()<start))
        test = np.flatnonzero(valid & (positions>=start) & (positions<stop))
        got = g[g.fold.eq(fold)]
        assert list(got.date) == list(x.date.iloc[test])
        for name,cols in COLS.items():
            matrix = x[cols].to_numpy()
            means = matrix[train].mean(0)
            std = matrix[train].std(0)
            std[std<1e-12] = 1
            a = np.column_stack([np.ones(len(train)),(matrix[train]-means)/std])
            penalty = np.diag([0.]+[np.sqrt(10.)]*len(cols))
            beta = np.linalg.lstsq(np.vstack([a,penalty]), np.r_[y[train],np.zeros(len(cols)+1)],rcond=None)[0]
            pred = np.column_stack([np.ones(len(test)),(matrix[test]-means)/std])@beta
            error = float(np.max(np.abs(pred-got[name+'_prediction'].to_numpy())))
            maximum = max(maximum,error)
            assert error < 1e-12
            q1,q2 = np.quantile(a@beta,[1/3,2/3],method='linear')
            expected = np.where(pred<=q1,-1,np.where(pred>=q2,1,0))
            np.testing.assert_array_equal(expected,got[name+'_group'].to_numpy())
    for frame,summary in [(g,result['all']),(g[g.C0031_first_entry],result['actual_C0031_first_entry'])]:
        for model in COLS:
            for target in ('gross','net_entry'):
                values = frame[target].to_numpy()
                low = frame[model+'_group'].to_numpy()==-1
                s = summary['models'][model]['groups']['-1'][target]
                assert int(low.sum()) == s['n']
                assert abs(values[low & (values>0)].sum()*100000-s['positive_yuan']) < 1e-7
                assert abs(-values[low & (values<0)].sum()*100000-s['negative_yuan']) < 1e-7
    prev = read(ROOT/'research/S015/experiments/EX014_20261023/others/publication_validation.json')
    from czsc_trader.research_tools import EvidenceRef
    ref = EvidenceRef.from_dict(prev['materials']['diagnosis_results.json'])
    history = read(ref.resolve(ROOT))
    window = history['accounts']['C0031']['maximum_drawdown']
    selected = g[g.C0031_first_entry & g.entry_date.gt(window['peak']) & g.entry_date.le(window['trough'])]
    prior_checks = EvidenceRef.from_dict(prev['materials']['verification.json'])
    expected = read(prior_checks.resolve(ROOT))['candidate_registration_hashes']
    actual = {p.name:sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research/registrations/S015/candidates').glob('*.json')}
    assert expected == actual
    save(HERE/'others/independent_audit.json', {
        'status':'PASS', 'label_price_quantity_fee_equations':'PASS',
        'independent_augmented_lstsq_replicated_model_fits':8,
        'max_prediction_difference':maximum, 'training_tercile_groups':'PASS',
        'selected_positive_negative_amounts':'PASS','candidate_registration_hashes_unchanged':117,
        'former_diagnosis_source':ref.to_dict(),
        'posthoc_explanatory_case_only': 'Previously diagnosed C0031 peak/trough calendar; selected after this result, no fitting/threshold change or second hypothesis test.',
        'case_window': {'peak':window['peak'],'trough':window['trough']},
        'case_entries':selected[['date','entry_date','gross','net_entry','PR_group','AllDaily_group']].to_dict('records'),
        'new_account_evaluations':0,
    })
    print({'audit':'PASS','prediction_difference':maximum,'case_entries':len(selected)},flush=True)


if __name__ == '__main__':
    main()
