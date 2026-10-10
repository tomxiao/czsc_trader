"""Declare all retained-account direction predicates before diagnostic execution."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    assert not (PROTOCOLS / 'method_reference.json').exists()
    assert not (PROTOCOLS / 'plan.json').exists()
    prior = read(ROOT / 'research/S013/experiments/EX038_20261011/protocols/plan.json')
    inputs = {'original33': read(ROOT / 'research/S013/experiments/EX033_20261011/protocols/diagnosis_reference.json'),
              'mean_center': read(ROOT / 'research/S013/assets/runs/EX028_20261011/account_references.json')['N1'],
              'body_center': read(ROOT / 'research/S013/assets/runs/EX029_20261011/account_references.json')['N1']}
    for value in inputs.values():
        ref = EvidenceRef.from_dict(value)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    paths = [ROOT / 'research/S013/experiments/EX036_20261011/src/confirmation_diagnosis_v2.py',
             ROOT / 'research/S013/experiments/EX033_20261011/src/diagnose.py']
    paths += [ROOT / 'research/S013/experiments/EX035_20261011/src' / name
              for name in ('common.py', 'account_reference.py', 'analysis_reference.py', 'ledger_reference.py')]
    for experiment in ('EX028_20261011', 'EX029_20261011'):
        cfg = next(x for x in read(ROOT / f'research/S013/experiments/{experiment}/protocols/plan.json')['configurations'] if x['label'] == 'N1')
        source = ROOT / f'research/S013/experiments/{experiment}/src' / cfg.get('source_directory', 'strategy_runtime')
        paths += [source / name for name in cfg['payload']['runtime']['source_files']]
    external = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in paths}
    method = {'name': 'Complete retained-account native entry-direction diagnosis', 'inputs': inputs,
              'source_files': {name: file_hash(SRC / name) for name in ('direction_diagnosis.py', 'focused_checks.py', 'common.py')},
              'external_source_files': external,
              'method': 'Authenticate original center plus all32 original joint full-domain points and MEAN/BODY centers, exact native identity, lineage, prepared binding, benchmark and cash ledgers. Independently reconstruct all causal ACF/rank/score/range/regime/full-state fields. At unchanged native opportunities and entries describe strict Close>previousClose and Close>Open; equality and negative cases retained. ALL and every native signal year, both routes and empty groups retained, including2019 signal for2020 execution. Preserve every original signal day and no state/cash counterfactual.',
              'unique_native_accounts': 35, 'new_account_evaluations': 0,
              'limits': 'Posthoc mechanism diagnosis on repeatedly seen S013 development pool. Original33 observations share one market path and are dependent. Predicate refusal counts cannot predict modified trades, profit, frequency or causal effect. No direction threshold search, economic veto, date removal or independent validation.'}
    ctx = context(1)
    write(SRC.parent / 'experiment.json', {'type': 'ExperimentRef', 'strategy_id': 'S013', 'experiment_id': EXPERIMENT.experiment_id})
    write(PROTOCOLS / 'method.json', method)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-direction-method',
        (PROTOCOLS / 'method.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'method_reference.json', reference.to_dict())
    plan = {'name': 'S013-EX039-complete-native-entry-direction-diagnosis', 'method_reference': reference.to_dict(),
            'input_references': inputs, 'external_source_files': external, 'source_files': method['source_files'],
            'mandate': prior['mandate'], 'authorization': prior['authorization'],
            'previous_delivery': read(ROOT / 'research/S013/experiments/EX038_20261011/protocols/delivery_reference.json'),
            'unique_native_accounts_reused': 35, 'new_account_evaluations': 0, 'new_business_configurations': 0,
            'economic_targets': 'Four original economic gates and all13 numeric domains unchanged. Diagnostics report-only.',
            'strongest_counterevidence': 'Earlier all-flat bull direction controls reduced trade frequency, while raw bear confirmation rarely refused entry. Bear direction may likewise remove profitable recoveries or sufficient trades; native old-path predicate counts are not modified-account profits.',
            'selection_history': 'EX037/38 six risk-exit centers failed. Stop width calibration; inspect already-existing entry direction before freezing the next structural test. All years and failed centers remain immutable.',
            'boundaries': 'RSCH S013 stage3 only; no prepare/eval/newdata/adjacentbatch/dependency/platform/freeze/PTE/prod/merge/tag/push.',
            'objective_achieved': False}
    write(PROTOCOLS / 'plan.json', plan)
    plan_reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-direction-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', plan_reference.to_dict())
    print({'declared': EXPERIMENT.experiment_id, 'new_accounts': 0, 'unique_reused': 35}, flush=True)


if __name__ == '__main__':
    main()
