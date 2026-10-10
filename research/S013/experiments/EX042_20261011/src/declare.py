"""Freeze a complete zero-new-account signal exit-anchor diagnostic method."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    assert not (PROTOCOLS / 'method_reference.json').exists()
    assert not (PROTOCOLS / 'plan.json').exists()
    prior = read(ROOT / 'research/S013/experiments/EX041_20261011/protocols/plan.json')
    inputs = {'original33': read(ROOT / 'research/S013/experiments/EX033_20261011/protocols/diagnosis_reference.json'),
              'mean_center': read(ROOT / 'research/S013/assets/runs/EX028_20261011/account_references.json')['N1'],
              'body_center': read(ROOT / 'research/S013/assets/runs/EX029_20261011/account_references.json')['N1'],
              'time_close': read(ROOT / 'research/S013/assets/runs/EX041_20261011/account_references.json')['N0'],
              'time_body': read(ROOT / 'research/S013/assets/runs/EX041_20261011/account_references.json')['N1']}
    for value in inputs.values():
        ref = EvidenceRef.from_dict(value)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    prior_diagnosis = read(ROOT / 'research/S013/experiments/EX016_20261011/protocols/previous_account_diagnosis_reference.json')
    prior_ref = EvidenceRef.from_dict(prior_diagnosis)
    assert prior_ref.experiment.strategy_id == 'S013' and file_hash(prior_ref.resolve(ROOT)) == prior_ref.sha256
    paths = [ROOT / 'research/S013/experiments/EX039_20261011/src/direction_diagnosis.py',
             ROOT / 'research/S013/experiments/EX036_20261011/src/confirmation_diagnosis_v2.py',
             ROOT / 'research/S013/experiments/EX033_20261011/src/diagnose.py',
             ROOT / 'research/S013/experiments/EX041_20261011/src/direction_oracle_v2.py']
    paths += [ROOT / 'research/S013/experiments/EX035_20261011/src' / name
              for name in ('common.py', 'account_reference.py', 'analysis_reference.py', 'ledger_reference.py')]
    for experiment, labels in (('EX028_20261011', ('N1',)), ('EX029_20261011', ('N1',)),
                               ('EX041_20261011', ('N0', 'N1'))):
        plan = read(ROOT / f'research/S013/experiments/{experiment}/protocols/plan.json')
        for label in labels:
            cfg = next(x for x in plan['configurations'] if x['label'] == label)
            source = ROOT / f'research/S013/experiments/{experiment}/src' / cfg.get('source_directory', 'strategy_runtime')
            paths += [source / name for name in cfg['payload']['runtime']['source_files']]
    external = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in paths}
    focused = read(ROOT / '.tmp/ex042-diagnosis/focused.json')
    source_checks = read(ROOT / '.tmp/ex042-diagnosis/source_checks.json')
    assert focused['status'] == source_checks['status'] == 'PURE_PASS'
    assert focused['new_account_evaluations'] == source_checks['new_account_evaluations'] == 0
    method = {'name': 'Complete retained-account causal signal exit-anchor context diagnosis', 'inputs': inputs,
        'source_files': {name: file_hash(SRC / name) for name in
            ('native_diagnosis.py', 'native_reference.py', 'anchor_diagnosis.py', 'focused_checks.py', 'source_checks.py', 'common.py')},
        'external_source_files': external, 'pure_prechecks': {'focused': focused, 'source_checks': source_checks},
        'method': 'Authenticate original center plus all32 original joint full-domain points and MEAN/BODY/TIME-CLOSE/TIME-BODY centers: exact native identity, lineage, prepared binding, full formal account, benchmark and cash ledgers. Independently reconstruct all causal features/full-state and bound-calendar signal-to-execution pairs. Reconstruct signal entry anchors and classify every bear TIME exit T Close strictly below/equal/above that signal anchor, at time of exit. Preserve every date, all exits, subsequent flat opportunities/refusals/any-route entries, nonTIME/NONE context, terminal no-reentry/open states and all years/empty groups. Remember causal signal context until any signal entry. Describe actual cash/fees and closed/open cycles by entry-source context; group sums must reproduce original complete actual daily/annual/whole account. No modified signals, cash replay or historical-profit deletion.',
        'unique_native_accounts': 37, 'new_account_evaluations': 0,
        'limits': 'Posthoc diagnosis on repeatedly seen S013 development pool. Original33 share one market path and are dependent, not independent trials. Signal exit price relative to signal anchor differs from actual cycle PnL including fills/fees. All categories and all years retained, including2019 signal for2020 execution. Actual cash grouping is descriptive, not profit of a changed policy; cross-year cycle PnL is not calendar-year return. No threshold search, successful-year selection, added economic veto or independent validation.'}
    ctx = context(1)
    write(SRC.parent / 'experiment.json', {'type': 'ExperimentRef', 'strategy_id': 'S013', 'experiment_id': EXPERIMENT.experiment_id})
    write(PROTOCOLS / 'method.json', method)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-anchor-method',
        (PROTOCOLS / 'method.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'method_reference.json', reference.to_dict())
    plan = {'name': 'S013-EX042-complete-native-signal-exit-anchor-diagnosis',
        'method_reference': reference.to_dict(), 'input_references': inputs,
        'external_source_files': external, 'source_files': method['source_files'],
        'mandate': prior['mandate'], 'authorization': prior['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX041_20261011/protocols/delivery_reference.json'),
        'unique_native_accounts_reused': 37, 'new_account_evaluations': 0, 'new_business_configurations': 0,
        'economic_targets': 'Four original economic gates and all13 numeric full domains unchanged. Diagnostics report-only.',
        'prior_anchor_counterevidence': {'reference': prior_diagnosis,
            'scope': 'EX016 already examined signal-relative exit price. Its2023 raw-bear TIME dedup excludes same-day raw-route changes; negative30 events next3signal-days averaged+.3690%, positive36 averaged-.1261%, with direction reversing at10days. Those overlapping future-window associations do not predict a changed account. EX042 retains route-changed exits too, everyyear and own37 native paths, actual calendar cash, and does not optimize future windows.'},
        'duplicate_review': {'result': 'No exact retained adverse-price-at-bear-TIME-exit entry-context gate found in S013 plan/strategy source review. EX041 gates all bearTIME reentries without anchor category; EX016 EXIT_NONPOSITIVE/NONNEGATIVE condition whether TIME exit occurs, preserving reentries.',
            'closest_sources': {name: file_hash(ROOT / name) for name in (
                'research/S013/experiments/EX041_20261011/src/strategy_runtime/strategies/acf_range.py',
                'research/S013/experiments/EX016_20261011/src/strategy_runtime/strategies/mechanism_range.py')},
            'limits': 'Source/protocol review and near-mechanism evidence; no claim that adverse-price reentry gating is effective or conceptually novel outside S013.'},
        'strongest_counterevidence': 'EX034/35 refresh waits and EX040 all-bear directions failed. EX041 narrow bearTIME reentry directions preserved116trades but made2023 about-1.25%; CLOSE passed annualDD while BODY still failed2024. A prior adverse signal-price state may also mark profitable recoveries; state classifications and actual PnL groups cannot predict the cash path or establish a reliable gate.',
        'selection_history': 'After complete EX041 negative evidence stop unconditional bearTIME direction expansion. Inspect causal exit-anchor category before choosing any successor; no date/threshold/predicate optimization from future outcomes. All original13 parameter points and failed extra centers retained.',
        'boundaries': 'RSCH S013 stage3 only; no prepare/eval/newdata/adjacentbatch/dependency/platform/freeze/PTE/prod/merge/tag/push.',
        'objective_achieved': False}
    write(PROTOCOLS / 'plan.json', plan)
    plan_ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-anchor-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', plan_ref.to_dict())
    print({'declared': EXPERIMENT.experiment_id, 'new_accounts': 0, 'unique_reused': 37}, flush=True)


if __name__ == '__main__':
    main()
