"""Independent EX061 verification from published CSV and retained predictions."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-next-research'
EXP = ROOT / 'research/S013/experiments/EX061_20261011'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def check():
    refs = read(EXP / 'protocols/result_references.json')
    resolved = {key: EvidenceRef.from_dict(value).resolve(ROOT) for key, value in refs.items()}
    result = read(resolved['statistics.json'])
    feature = pd.read_csv(resolved['features.csv'], index_col='signal_date', float_precision='round_trip')
    labels = pd.read_csv(resolved['labels.csv'], index_col='signal_date', float_precision='round_trip')
    opportunity = pd.read_csv(resolved['opportunity.csv'], index_col='signal_date').iloc[:, 0]
    for frame in (feature, labels, opportunity):
        frame.index = pd.to_datetime(frame.index)
    assert feature.index.equals(labels.index) and feature.index.equals(opportunity.index)
    assert len(feature) == 1635 and feature.index.is_unique and feature.index.is_monotonic_increasing
    assert feature.index[0] == pd.Timestamp('2020-01-02')
    assert feature.index[-1] == pd.Timestamp('2026-09-29')
    assert opportunity.dtype == bool and opportunity.notna().all()
    method = result['method']
    controls = feature[method['controls']].to_numpy()
    all_x = feature[[*method['controls'], *method['components']]].to_numpy()
    sessions = feature.index.append(pd.DatetimeIndex(['2026-09-30']))
    checks = ['published_evidence_integrity', 'signal_grid_alignment']
    maturity_rows = []
    for label, horizon in method['labels'].items():
        ends = pd.to_datetime(labels['label_end_' + label]).astype('datetime64[ns]')
        expected = pd.Series(pd.NaT, index=feature.index, dtype='datetime64[ns]')
        valid_n = len(sessions) - horizon - 1
        expected.iloc[:valid_n] = sessions[horizon + 1:].to_numpy()
        pd.testing.assert_series_equal(ends, expected, check_names=False)
        np.testing.assert_array_equal(labels[label].notna(), ends.notna())
        checks.append(label + '::h_complete_execution_sessions')
    for scope, panel in result['scopes'].items():
        selected = np.ones(len(feature), dtype=bool) if scope == 'all' else opportunity.to_numpy()
        for label in method['labels']:
            y = labels[label].to_numpy()
            ends = pd.to_datetime(labels['label_end_' + label]).astype('datetime64[ns]')
            finite = np.isfinite(all_x).all(axis=1) & np.isfinite(y)
            block = panel['labels'][label]
            for component in method['components']:
                x = feature[component].to_numpy()
                expected = block['components'][component]
                good = selected & np.isfinite(x) & np.isfinite(y)
                assert int(good.sum()) == expected['spearman']['n']
                np.testing.assert_allclose(spearmanr(x[good], y[good]).statistic,
                                           expected['spearman']['value'], rtol=0, atol=1e-14)
                good &= np.isfinite(controls).all(axis=1)
                assert int(good.sum()) == expected['partial_rank_ic']['n']
                design = np.column_stack([np.ones(good.sum()),
                    *[rankdata(c) for c in controls[good].T]])
                residuals = []
                for values in (x[good], y[good]):
                    ranks = rankdata(values)
                    residuals.append(ranks - design @ np.linalg.lstsq(design, ranks, rcond=None)[0])
                np.testing.assert_allclose(np.corrcoef(*residuals)[0, 1],
                                           expected['partial_rank_ic']['value'], rtol=0, atol=1e-13)
                checks.append(scope + '::' + label + '::' + component + '::independent_ic')
            wf = block['walk_forward']
            for year, row in wf['yearly'].items():
                year_int = int(year)
                first = feature.index[feature.index.year == year_int][0]
                assert first == pd.Timestamp(row['first_actual_signaldate'])
                train = selected & finite & (feature.index.year >= 2020) & (feature.index.year < year_int)
                train &= (ends < first).to_numpy()
                test = selected & finite & (feature.index.year == year_int)
                assert int(train.sum()) == row['common_train_n']
                assert int(test.sum()) == row['common_test_n']
                latest = ends[train].max() if train.any() else pd.NaT
                assert latest < first
                assert latest == pd.Timestamp(row['latest_train_label_end'])
                maturity_rows.append({'scope': scope, 'label': label, 'year': year_int,
                                      'train_n': int(train.sum()), 'test_n': int(test.sum()),
                                      'latest_train_label_end': latest.isoformat(),
                                      'first_test_signal': first.isoformat()})
                checks.append(scope + '::' + label + '::' + year + '::strict_maturity')
            common_dates = None
            for model, records in wf['prediction_records'].items():
                dates = [r['signaldate'] for r in records]
                assert len(dates) == len(set(dates))
                if common_dates is None:
                    common_dates = dates
                else:
                    assert dates == common_dates
                truth = np.array([r['target'] for r in records])
                prediction = np.array([r['prediction'] for r in records])
                baseline = np.array([r['baseline'] for r in records])
                index = pd.DatetimeIndex(pd.to_datetime(dates))
                np.testing.assert_array_equal(truth, labels.loc[index, label].to_numpy())
                metrics = wf['aggregate_models'][model]
                assert len(records) == metrics['n']
                np.testing.assert_allclose(np.mean((truth - prediction) ** 2), metrics['mse'], rtol=0, atol=1e-14)
                np.testing.assert_allclose(np.mean((truth - baseline) ** 2), metrics['baseline_mse'], rtol=0, atol=1e-14)
                for year, row in wf['yearly'].items():
                    use = index.year == int(year)
                    yearly_metric = row['models'][model]
                    assert int(use.sum()) == (yearly_metric['n'] if yearly_metric['mse'] is not None else 0)
                    if use.any():
                        np.testing.assert_allclose(np.mean((truth[use] - prediction[use]) ** 2),
                                                   yearly_metric['mse'], rtol=0, atol=1e-14)
                checks.append(scope + '::' + label + '::' + model + '::prediction_mse')
    output = {'status': 'PASS', 'checks': checks, 'check_count': len(checks),
              'maturity_records': maturity_rows,
              'published_input_references': {key: refs[key] for key in ('features.csv', 'labels.csv', 'opportunity.csv', 'statistics.json')},
              'source_and_selected_evidence_hashes': 'PASS', 'new_account_runs': 0,
              'scope': 'Independent Spearman and partial OLS from published CSV; exact session maturity, annual train/test counts, retained truth and aggregate/year MSE plus identical model dates. Bootstrap and model fitting not rerun.'}
    (WORK / 'verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print({'actual_checks': 'PASS', 'count': len(checks), 'new_accounts': 0})


if __name__ == '__main__':
    check()
