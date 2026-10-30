"""Publish the completed, source-bound account decision without advancing stage."""
from common import (ROOT, WORK, REPOSITORY, EXPERIMENT, PARAMETERS, context,
    read, save, digest, material, authenticate)
from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)


def main():
    analysis = read(WORK/'others/analysis.json')
    checked = read(WORK/'others/result_validation.json')
    if (analysis['status'] != 'PASS' or checked['status'] != 'PASS'
            or checked['analysis_sha256'] != digest(WORK/'others/analysis.json')
            or checked['verification_source_sha256'] != digest(WORK/'src/verify.py')
            or analysis['analysis_source_sha256'] != digest(WORK/'src/analyze.py')
            or analysis['account_manifest_sha256'] != digest(WORK/'others/accounts.json')
            or checked['account_manifest_sha256'] != digest(WORK/'others/accounts.json')):
        raise ValueError('Current source-bound independent account checks required')
    for relative, ref in read(WORK/'others/pre_account_evidence.json').items():
        if digest(WORK/relative) != digest(authenticate(ref)):
            raise ValueError('Frozen formal account source changed: ' + relative)
    if (read(WORK/'others/control_equivalence.json')['status'] != 'PASS'
            or read(WORK/'others/signal_validation.json')['status'] != 'PASS'):
        raise ValueError('Control and signal identity checks required')
    report = (WORK/'report.md').read_text(encoding='utf-8')
    table_checks = {}
    for key in PARAMETERS:
        rows = [line for line in report.splitlines() if line.startswith('|') and ' / '+key in line]
        if len(rows) != 1:
            raise ValueError('Report main table row missing or repeated: ' + key)
        values = [float(v.strip().replace('%', '').replace('−', '-')) for v in rows[0].split('|')[2:-1]]
        r = analysis['summaries'][key]['candidate']
        expected = [100*r['annualized_return'], 100*r['bar_max_drawdown'], r['closed_cycles'],
            r['rolling_60_closed_cycle_median'], 100*r['coverage_at_least_three'], 100*r['holding_bar_fraction']]
        if len(values) != len(expected) or any(abs(x-y) > .00501 for x, y in zip(values, expected, strict=True)):
            raise ValueError('Main report table differs from the authenticated account: ' + key)
        table_checks[key] = 'PASS'
    for year in range(2019, 2026):
        row = next(line for line in report.splitlines() if line.startswith('|'+str(year)+'|'))
        values = [float(v.strip().replace('%', '').replace('−', '-')) for v in row.split('|')[2:-1]]
        expected = [analysis['summaries']['C0061']['candidate']['year_returns'][str(year)]*100,
            analysis['summaries']['C0062']['candidate']['year_returns'][str(year)]*100,
            analysis['summaries']['C0061']['benchmark']['year_returns'][str(year)]*100]
        if len(values) != 3 or any(abs(x-y) > .00501 for x, y in zip(values, expected, strict=True)):
            raise ValueError('Annual report row differs: ' + str(year))
    current, control = (analysis['summaries'][key]['candidate'] for key in ('C0061', 'C0062'))
    if not (current['annualized_return'] < control['annualized_return']
            and current['bar_max_drawdown'] > control['bar_max_drawdown']
            and analysis['summaries']['C0061']['all_goals_met'] is False):
        raise ValueError('Declared stop decision is not supported by the actual comparison')
    save(WORK/'others/judgment.json', {'status': 'COMPLETED', 'decision': 'STOP_M008_FIXED65_SIMPLIFICATION',
        'analysis_sha256': digest(WORK/'others/analysis.json'), 'main_report_table_checks': table_checks,
        'annual_report_rows': 'PASS', 'new_economic_configurations': 1, 'technical_control_replays': 1,
        'shared_benchmark_runs': 1, 'new_public_diagnoses': 1, 'candidate_registration': 0,
        'stage_three_recommended': False, 'new_followup_accounts_started': 0})
    research = context()
    selected = [*analysis['source_accounts'].values(), analysis['public_diagnosis']['reference']]
    for eid in ('EX025_20261029', 'EX026_20261029', 'EX027_20261029'):
        retained = read(ROOT/'research/S017/experiments'/eid/'report_ref.json')['report']
        authenticate(retained)
        selected.append(retained)
    materials = {}
    paths = [*sorted((WORK/'src').glob('*.py')), *sorted((WORK/'protocols').glob('*.*')),
        *sorted(p for p in (WORK/'others').glob('*.*') if p.name not in ('publication.json', 'public_diagnosis.json'))]
    for i, path in enumerate(paths):
        ref = material(research, 'completed-result-'+str(i), path)
        materials[str(path.relative_to(WORK)).replace('\\', '/')] = ref.to_dict()
        selected.append(ref.to_dict())
    associated = tuple(dict.fromkeys(EvidenceRef.from_dict(r) for r in selected))
    pointer = WORK/'report_ref.json'
    previous = EvidenceRef.from_dict(read(pointer)['report']) if pointer.exists() else None
    result = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK/'report.md'),
        ExperimentOutcome.COMPLETED, associated, previous))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report': result.to_dict(), 'materials': materials,
        'validation': validation.to_dict()})
    if validation.status.value != 'PASS':
        raise ValueError('Report publication validation failed')
    print('REPORT_PUBLICATION_PASS', result.sha256, flush=True)


if __name__ == '__main__':
    main()
