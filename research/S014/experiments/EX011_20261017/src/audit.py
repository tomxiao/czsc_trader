"""Audit actual upstream receipts and immutable research references, offline."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

from czsc_trader.application import RepositoryContext, validate_delivery
from czsc_trader.research_tools import DeliveryContent, DeliveryReference, EvidenceRef, ValidationStatus

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]


def main():
    checks = []

    def check(name, passed):
        if not passed:
            raise AssertionError(name)
        checks.append({'name': name, 'status': 'PASS'})

    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    first = read(EXPERIMENT/'others/upstream_verification.json')
    second = read(EXPERIMENT/'others/default_fields_verification.json')
    calls = first['source_calls'] + second['source_calls']
    check('exactly_two_counted_attempts', len(calls) == 2 and first['new_source_calls'] == second['new_source_calls'] == 1)
    check('exact_company_window_only', all(x['api'] == 'anns_d' and x['params'] == {
        'ts_code': '600722.SH', 'start_date': '20200101', 'end_date': '20261015'} for x in calls))
    check('optional_timestamp_is_only_field_change', calls[0]['fields'] == calls[1]['fields'] + ',rec_time')
    check('both_http_success_business_failure', all(x['http_status'] == 200 and x['vendor_code'] == 40203 for x in calls))
    check('explicit_permission_message_evidence', calls[1]['vendor_message_class'] == 'PERMISSION_RELATED'
        and '没有接口访问权限' in calls[1]['vendor_message_chinese_projection'])
    check('both_typed_error_contexts_agree', all(x['error_type'] == 'SourceRequestError'
        and x['error_context']['vendor_code'] == 40203 for x in (first, second)))
    check('no_catalogue_obtained', not first['catalogue_received'] and not second['catalogue_received']
        and not tuple((EXPERIMENT/'others').glob('*catalogue.csv')))
    check('history_and_timestamp_remain_unknown', all(x['history_coverage'] == x['historical_publication_time'] == 'UNVERIFIED' for x in (first, second)))
    check('budget_conservation', first['cumulative_source_calls'] == 49 and first['remaining_source_calls'] == 1
        and second['cumulative_source_calls'] == 50 and second['remaining_source_calls'] == 0 and second['experiment_source_calls'] == 2)
    refs = {}
    for name in ('published_design', 'published_followup'):
        refs.update({n: EvidenceRef.from_dict(v) for n, v in read(EXPERIMENT/f'protocols/{name}.json').items()})
    check('prospective_published_bytes_unchanged', all(sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256 for ref in refs.values())
        and sha256((EXPERIMENT/'src/verify_upstream.py').read_bytes()).hexdigest() == refs['verification-program'].sha256
        and sha256((EXPERIMENT/'src/verify_default_fields.py').read_bytes()).hexdigest() == refs['default-fields-program'].sha256)
    design = read(EXPERIMENT/'protocols/design.json')
    followup = read(EXPERIMENT/'protocols/followup_design.json')
    check('approved_scope_and_followup_basis', design['prior_source_calls_used'] == 48 and design['remaining_source_calls_before'] == 2
        and followup['basis'] == first and design['no_returns_join'] and design['no_new_components'] and design['no_platform_changes'])
    for p in (EXPERIMENT/'src').glob('*.py'):
        ast.parse(p.read_text(encoding='utf-8'))
    check('source_syntax_valid_offline', True)
    check('duplicate_attempt_guards_present', all('guard.exists()' in (EXPERIMENT/f'src/{n}.py').read_text(encoding='utf-8')
        for n in ('verify_upstream', 'verify_default_fields')))
    prior = read(ROOT/'research/S014/experiments/EX010_20261017/others/result.json')
    mandate = read(ROOT/'research/S014/experiments/EX003_20261016/others/result.json')
    repo = RepositoryContext.discover(ROOT)
    check('prior_deliveries_full_pass', all(validate_delivery(repo, DeliveryReference.from_dict(x['delivery'])).status is ValidationStatus.PASS
        for x in (prior, mandate)))
    old = DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/7/delivery.json')['content'])
    check('inherited_evidence_hashes', all(sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256 for ref in old.evidence))
    check('prior_panel_25_definitions_two_supported', len(old.payload.components) == 25
        and sum(any(str(t.status) == 'SUPPORTED' for t in e.tests) for e in old.payload.components) == 2)
    report = (EXPERIMENT/'protocols/report.md').read_text(encoding='utf-8')
    check('all_local_report_links_resolve', all((EXPERIMENT/'protocols'/link).resolve().exists()
        for link in re.findall(r'\]\(([^)]+)\)', report) if not link.startswith('https://')))
    check('no_false_readiness_or_phase_acceptance', '仍未核验' in report and '阶段二未完成' in report and '剩余0' in report)
    manifest = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha256(p.read_bytes()).hexdigest()}
        for folder in ('src', 'protocols', 'others') for p in sorted((EXPERIMENT/folder).glob('*'))
        if p.is_file() and p.name not in ('audit.json', 'result.json', 'report_copy_verification.json', 'report.md')]
    manifest.append({'path': (EXPERIMENT/'protocols/report.md').relative_to(ROOT).as_posix(),
        'sha256': sha256((EXPERIMENT/'protocols/report.md').read_bytes()).hexdigest()})
    result = {'status': 'PASS', 'checks': checks, 'manifest': manifest, 'inherited_evidence_refs': len(old.evidence),
        'scope': 'Offline request/evidence integrity checks; no announcement coverage, timestamp or economic acceptance.'}
    (EXPERIMENT/'others/audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'checks': len(checks), 'inherited_evidence_refs': len(old.evidence)}))


if __name__ == '__main__':
    main()
