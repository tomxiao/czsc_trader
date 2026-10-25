"""Verify the authorized source-only adaptation and pure calendar boundaries."""
# ruff: noqa: E402 -- avoid bytecode writes before loading authenticated sources
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from czsc_trader.application import RepositoryContext, load_candidate
from strategy_manager import CandidateKey
from strategy_runtime import StrategyCandidate, StrategyInit, StrategyRuntime, TradableWindow, implementation_sha256


ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
SOURCE = HOME / 'src/strategy_runtime'
OLD_CONTENT = 'abf26e331cac4cd030c30aa5f84269e0471d3a4c31b36f5e9f8a0dbf687beda1'
PARAMETERS = {'center_kind': 'median', 'lookback': 3, 'allocation': 1.0,
              'minimum_repair_space': 0.0017298986606429072}


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def save(path, value):
    if path.exists():
        raise FileExistsError('Preserve prior source-check evidence')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    outputs = [HOME / 'others/source_change.json', HOME / 'others/calendar_boundary.json']
    assert not any(path.exists() for path in outputs), 'Preserve existing check outputs'
    repository = RepositoryContext.discover(ROOT)
    old = load_candidate(repository, CandidateKey('S015', 'C9304'))
    runtime = StrategyRuntime()
    old_identity = runtime.identify(old, dependencies=())
    assert old_identity.content_sha256 == OLD_CONTENT
    assert dict(old.payload['parameters']) == PARAMETERS
    files = tuple(old.payload['runtime']['source_files'])
    assert 'strategies/price_process.py' in files
    assert sorted(p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob('*.py')) == sorted(files)
    rows, diffs, original_bytes = [], [], {}
    for name in files:
        before = (old.source_root / name).read_bytes()
        after = (SOURCE / name).read_bytes()
        original_bytes[name] = before
        expected = before
        if name == 'strategies/price_process.py':
            constant = b'LAST = date(2026, 10, 21)\r\n'
            guard = b'if tradable_window.start < FIRST or tradable_window.end > LAST:'
            assert before.count(constant) == before.count(guard) == 1
            expected = before.replace(constant, b'').replace(guard, b'if tradable_window.start < FIRST:')
            assert after.count(b'outside approved development windows') == before.count(b'outside approved development windows') == 1
        assert after == expected, f'Unexpected byte change: {name}'
        diff = ''.join(unified_diff(before.decode('utf-8').splitlines(keepends=True),
                                    after.decode('utf-8').splitlines(keepends=True),
                                    fromfile='C9304/' + name, tofile='C9700/' + name))
        if diff:
            diffs.append({'path': name, 'unified_diff': diff})
        rows.append({'path': name, 'old_file_sha256': sha256(before).hexdigest(),
                     'new_file_sha256': sha256(after).hexdigest(), 'old_bytes': len(before),
                     'new_bytes': len(after), 'changed': before != after,
                     'exact_allowed_transformation': after == expected})
    assert len(diffs) == 1
    payload = plain(old.payload)
    payload['runtime']['source_sha256'] = implementation_sha256(files, source_root=SOURCE)
    new = StrategyCandidate('S015', 'C9700', payload, SOURCE)
    new_identity = runtime.identify(new, dependencies=())
    assert new_identity.content_sha256 != OLD_CONTENT
    assert plain(new.payload['parameters']) == plain(old.payload['parameters']) == PARAMETERS
    for key in payload:
        if key != 'runtime':
            assert plain(new.payload[key]) == plain(old.payload[key])
    assert {k: v for k, v in payload['runtime'].items() if k != 'source_sha256'} == {
        k: plain(v) for k, v in old.payload['runtime'].items() if k != 'source_sha256'}
    checks = []
    dates = (date(2024, 12, 31), date(2025, 1, 2), date(2026, 10, 21),
             date(2026, 10, 22), date(2026, 10, 26), date(2027, 1, 4))
    for candidate in (old, new):
        for day in dates:
            expected_acceptance = day >= date(2025, 1, 2) and (
                candidate.candidate_id == 'C9700' or day <= date(2026, 10, 21))
            instance = runtime.create(StrategyInit(candidate, TradableWindow(day, day),
                ROOT / '.tmp/s015-ex082/calendar-boundary' / candidate.candidate_id / day.isoformat()))
            try:
                request = instance.calendar_request()
            except ValueError as error:
                assert not expected_acceptance
                assert str(error) == 'outside approved development windows'
                row = {'status': 'REJECTED', 'error': str(error)}
            else:
                assert expected_acceptance
                assert str(request.start) == '2024-09-09'
                assert str(request.end) == str(request.required_cutoff) == day.isoformat()
                row = {'status': 'ACCEPTED_REQUEST', 'calendar_start': str(request.start),
                       'calendar_end': str(request.end), 'required_cutoff': str(request.required_cutoff)}
            checks.append({'candidate_id': candidate.candidate_id, 'session': day.isoformat(), **row})
    assert runtime.identify(load_candidate(repository, CandidateKey('S015', 'C9304')),
                            dependencies=()).content_sha256 == OLD_CONTENT
    assert all((old.source_root / name).read_bytes() == value for name, value in original_bytes.items())
    save(outputs[0], {'status': 'PASS', 'old_candidate_id': 'C9304', 'new_candidate_id': 'C9700',
        'old_content_sha256': old_identity.content_sha256, 'new_content_sha256': new_identity.content_sha256,
        'old_source_sha256': old_identity.source_sha256, 'new_source_sha256': new_identity.source_sha256,
        'source_root': SOURCE.relative_to(ROOT).as_posix(), 'parameters': PARAMETERS,
        'parameters_unchanged': True, 'old_source_unchanged': True,
        'allowed_change': 'Remove LAST definition and only the calendar_request end > LAST guard; preserve FIRST, original error text and all other source bytes.',
        'source_files': rows, 'minimal_diff': diffs,
        'registration': 'NOT_REQUESTED', 'research_evaluation': 'NOT_REQUESTED'})
    save(outputs[1], {'status': 'PASS', 'old_content_sha256': old_identity.content_sha256,
        'new_content_sha256': new_identity.content_sha256, 'checks': checks,
        'new_market_data_fetched': False,
        'method': 'Public StrategyRuntime.create and calendar_request only; no supplier, calendar fetch or account execution.',
        'limit': 'Request construction does not establish future input availability, execution behavior or independent profitability.'})
    print(json.dumps({'status': 'PASS', 'new_content_sha256': new_identity.content_sha256,
                      'new_source_sha256': new_identity.source_sha256, 'calendar_checks': len(checks)}))


if __name__ == '__main__':
    main()
