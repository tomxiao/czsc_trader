"""Focused identity, inspection-output and report-link verification; no account reruns."""
from hashlib import sha256
import re

from inspect_selected import ROOT, EROOT, CONTENT, KEY, read, save
from publish_inspection import inputs
from strategy_manager import freeze_contracts as f


def main():
    report, _ = inputs()
    assert report.origin.candidate == KEY and report.origin.content_sha256 == CONTENT
    protocol = read(EROOT / 'protocols/inspection.json')
    assert report.protocol.to_dict() == protocol['protocol']
    assert {x.check for x in report.checks} == set(f.InspectionCheck)
    assert report.protocol.tolerance == 0
    assert [(x.window_id, x.scenario_id) for x in report.protocol.coordinates] == [
        ('full', 'standard'), ('full', 'fee_x2')]
    if report.plan:
        assert read(EROOT / 'others/freeze_plan.json') == report.plan.to_dict()
        assert report.plan.version == 'v1' and report.plan.parent_version is None
        assert (report.plan.selection_data_cutoff, report.plan.forward_start) == ('2026-10-21', '2026-10-22')
        expected = f.FreezeSubject(KEY, CONTENT, report.reference, report.plan.sha256, 'v1')
        assert read(EROOT / 'others/freeze_approval_subject.json') == expected.to_dict()
        for file in report.plan.source_files:
            file.source.resolve(ROOT)
        report.plan.payload.resolve(ROOT)
        report.plan.runtime_binding.resolve(ROOT)
        for reference in report.plan.registration_evidence:
            reference.resolve(ROOT)
    refs = {ref for check in report.checks for ref in check.evidence}
    for ref in refs:
        ref.resolve(ROOT)
    details = []
    for ref in refs:
        item = read(ref.resolve(ROOT))
        if isinstance(item, dict) and 'release_replays' in item and 'coverage' in item:
            details.append(item)
    if report.status is f.InspectionStatus.PASS:
        assert len(details) == 1
        detail = details[0]
        assert detail['coverage'] == protocol['protocol']['coordinates']
        assert detail['errors'] == detail['signal_errors'] == detail['unavailable_references'] == []
        assert len(detail['audits']) == len(detail['comparisons']) == len(detail['signal_equivalence']) == 4
        assert all(x['status'] == 'PASS' for x in detail['audits'])
        assert all(x['status'] == 'EQUIVALENT' for x in detail['comparisons'])
        assert all(x is True for x in detail['signal_equivalence'])
        assert len(detail['release_replays']) == 2
    assert not (ROOT / 'strategies/S015').exists(), 'Unexpected frozen family appeared'
    assert not any((ROOT / 'research/S015/freeze_requests').glob('*/research_request.json'))
    text = (EROOT / 'report.md').read_text(encoding='utf-8')
    assert sha256(text.encode()).hexdigest() == read(EROOT / 'others/publication_precheck.json')['report_sha256']
    links = re.findall(r'\]\(([^)]+)\)', text)
    for link in links:
        assert not link.startswith(('http', '/', 'file:')) and ':/' not in link
        assert (EROOT / link.split('#')[0]).resolve().exists(), link
    result = {
        'status': 'PASS', 'scope': 'identity, actual inspection details, exact approval sidecars, report links and absence of freeze; no whole-repository regression',
        'inspection_status': report.status.value, 'inspection_sha256': report.sha256,
        'checks': len(report.checks), 'protocol_coordinates': len(report.protocol.coordinates),
        'verified_research_evidence_refs': len(refs), 'report_links': len(links),
        'actual_signal_comparisons': sum(len(x['signal_equivalence']) for x in details),
        'actual_ledger_comparisons': sum(len(x['comparisons']) for x in details),
        'actual_ledger_audits': sum(len(x['audits']) for x in details),
        'source_hashes': {path.name: sha256(path.read_bytes()).hexdigest() for path in sorted((EROOT / 'src').glob('*.py'))},
    }
    save(EROOT / 'others/final_checks.json', result)
    print({key: value for key, value in result.items() if key != 'source_hashes'}, flush=True)


if __name__ == '__main__':
    main()
