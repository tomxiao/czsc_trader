"""Publish the diagnosis against authenticated predecessors and retained numbers."""
# ruff: noqa: E402
import json
import os
import re
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
os.environ['TEMP'] = os.environ['TMP'] = str(ROOT / '.tmp')
from dataflows import BarFrequency, ProviderConfig
from strategy_runtime import (
    ResearchExecutionSpec, UsEquitySpec, AccountPolicy, CashAvailabilityPolicy, ExecutionResources,
)
from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, validate_experiment,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, EvidenceRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope,
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding='utf-8', newline='\n')


def main():
    facts = read(WORK / 'others/diagnostic_facts.json')
    if facts['status'] != 'PASS' or len(facts['accounts']) != 9:
        raise ValueError('Current source-bound numeric audit required')
    for relative, expected in facts['source_hashes'].items():
        if digest(ROOT / relative) != expected:
            raise ValueError('Predecessor source changed: ' + relative)
    report = (WORK / 'report.md').read_text(encoding='utf-8')
    table_checks = {}
    for key, row in facts['accounts'].items():
        lines = [line for line in report.splitlines() if line.startswith('|') and f'（{key}）' in line]
        if len(lines) != 1:
            raise ValueError('Account table row missing or duplicated: ' + key)
        cells = lines[0].split('|')[2:-1]
        expected = [row['annualized_return'] * 100, row['bar_max_drawdown'] * 100,
                    row['closed_cycles'], row['rolling_60_closed_cycle_median'],
                    row['coverage_at_least_three'] * 100, row['holding_bar_fraction'] * 100]
        if len(cells) != len(expected):
            raise ValueError('Unexpected table layout')
        for text, value in zip(cells, expected, strict=True):
            actual = float(text.strip().replace('%', '').replace('−', '-'))
            if abs(actual - value) > .00501:
                raise ValueError('Report table differs from source: ' + key)
        table_checks[key] = 'PASS'
    batch_sources = [
        'research/RSCH_AGENT.md', 'research/S017/HANDOFF.md',
        'research/S017/deliveries/MANDATE/3/report.md',
        'research/S017/deliveries/PROTOTYPES/7/report.md',
        'research/S017/materials/DIAGNOSIS_HANDOFF_20261030.md',
        'research/S017/materials/CONDITIONAL_REPAIR_CLOSEOUT_20261030.md',
        'research/S017/materials/RESEARCH_REDESIGN_REVIEW_20261030.md',
        'research/S017/materials/mechanism_index.json',
    ]
    # These hashes record exact working sources; no stage-delivery recertification is claimed.
    save(WORK / 'others/review_validation.json', {
        'status': 'PASS', 'numeric_facts_sha256': digest(WORK / 'others/diagnostic_facts.json'),
        'collector_source_sha256': digest(WORK / 'src/collect.py'),
        'report_table_checks': table_checks,
        'review_source_hashes': {p: digest(ROOT / p) for p in batch_sources},
        'scope': 'Nine source-bound report rows and source immutability; no new strategy tests or full regression.',
    })
    repository = RepositoryContext.discover(ROOT)
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    research = create_research_context(repository, ResearchBatchRef('S017'),
        providers=ProviderConfig(bindings={}), execution_spec=spec,
        resources=ExecutionResources(max_workers=1, native_threads_per_worker=1, random_seed=17))
    experiment = ExperimentRef('S017', WORK.name)
    selected = [*facts['report_refs'], *facts['account_refs'].values(), *facts['public_diagnosis_refs']]
    materials = {}
    paths = [*sorted((WORK / 'src').glob('*.py')), *sorted((WORK / 'protocols').glob('*.md')),
             *sorted(p for p in (WORK / 'others').glob('*.json') if p.name != 'publication.json')]
    for i, path in enumerate(paths):
        reference = publish_evidence(research, MaterialEvidenceWrite(experiment,
            f'diagnosis-material-{i}', path.read_bytes(),
            {'.json': 'application/json', '.md': 'text/markdown', '.py': 'text/x-python'}[path.suffix],
            path.suffix[1:]))
        materials[str(path.relative_to(WORK)).replace('\\', '/')] = reference.to_dict()
        selected.append(reference.to_dict())
    associated = tuple(dict.fromkeys(EvidenceRef.from_dict(r) for r in selected))
    pointer = WORK / 'report_ref.json'
    previous = EvidenceRef.from_dict(read(pointer)['report']) if pointer.exists() else None
    reference = publish_evidence(research, ExperimentReportWrite(experiment, digest(WORK / 'report.md'),
        ExperimentOutcome.COMPLETED, associated, previous))
    checked = validate_experiment(repository, ExperimentValidationRequest(
        experiment, ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK / 'others/publication.json', {
        'report': reference.to_dict(), 'materials': materials, 'validation': checked.to_dict(),
        'historical_reports': len(facts['report_refs']), 'existing_accounts': len(facts['account_refs']),
        'existing_public_diagnoses': len(facts['public_diagnosis_refs']),
    })
    if checked.status.value != 'PASS':
        raise ValueError('Diagnosis publication failed')
    for link in re.findall(r'\]\(([^)]+)\)', report):
        if not link.startswith(('http:', 'https:', '#')) and not (WORK / link).is_file():
            raise ValueError('Report link missing: ' + link)
    print('DIAGNOSIS_REPORT_PUBLICATION_PASS', reference.sha256, flush=True)


if __name__ == '__main__':
    main()
