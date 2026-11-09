# Risk ownership: INFRA-02
"""Bounded access-conflict handling at the two actual publication boundaries."""

import json
from pathlib import Path

import pytest

from czsc_trader.application import runtime_migration
from paper_trading_engine import file_publication, srt_advice_client


@pytest.fixture
def publication(request, tmp_path):
    if request.param == "upgrade":
        target = tmp_path / "version.json"
        target.write_bytes(b"old-version")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        expected = b"new-version"
        return (runtime_migration, target, scratch, expected,
                lambda: runtime_migration._upgrade_write(target, expected, scratch))
    root = tmp_path / "account"
    root.mkdir()
    srt_advice_client.SrtAdviceClient._write_index(root, {"revision": "old"})
    index = {"revision": "new"}
    expected_index = dict(index, index_sha256=srt_advice_client.canonical_sha256(index))
    expected = (json.dumps(expected_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    return (file_publication, root / "current.json", root / ".tmp", expected,
            lambda: srt_advice_client.SrtAdviceClient._write_index(root, index))


@pytest.mark.parametrize('publication,codes,windows,succeeds', [
    pytest.param('upgrade', (32, 32), True, True, id='INFRA-02-C03'),
    pytest.param('upgrade', (5,) * 5, True, False, id='INFRA-02-C04'),
    pytest.param('upgrade', (2,), True, False, id='INFRA-02-C05'),
    pytest.param('account-index', (32, 32), True, True, id='INFRA-02-X01'),
    pytest.param('account-index', (5,) * 5, True, False, id='INFRA-02-X02'),
    pytest.param('account-index', (2,), True, False, id='INFRA-02-X03'),
], indirect=['publication'])

def test_atomic_publication_preserves_bytes_and_bounds_conflicts(
        publication, monkeypatch, caplog, codes, windows, succeeds):
    module, target, scratch, expected, publish = publication
    before = target.read_bytes()
    delays = (0.025, 0.050, 0.100, 0.200) if windows else ()
    monkeypatch.setattr(module, "_FILE_REPLACE_DELAYS", delays)
    errors = []
    for code in codes:
        error = PermissionError("synthetic access error") if code is None else OSError("synthetic Windows error")
        if code is not None:
            error.winerror = code
        errors.append(error)
    attempts, waits = [], []
    original_replace = module.os.replace

    def replace(source, destination):
        if Path(destination) != target:
            return original_replace(source, destination)
        # Every failed attempt leaves the old committed contents visible.
        assert target.read_bytes() == before
        assert Path(source).read_bytes() == expected
        attempts.append(Path(source))
        if len(attempts) <= len(errors):
            raise errors[len(attempts) - 1]
        return original_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", replace)
    monkeypatch.setattr(module.clock, "sleep", waits.append)
    if succeeds:
        publish()
        assert target.read_bytes() == expected
    else:
        with pytest.raises(OSError) as caught:
            publish()
        assert caught.value is errors[-1]
        assert target.read_bytes() == before
    expected_attempts = len(codes) + int(succeeds)
    assert len(attempts) == expected_attempts
    assert len(set(attempts)) == 1  # The same completed temporary file is retried.
    assert waits == list(delays[:expected_attempts - 1])
    assert not scratch.exists() or not list(scratch.iterdir())
    messages = [record.message for record in caplog.records if record.name == module.__name__]
    if expected_attempts == 1:
        assert messages == []
    else:
        outcome = "recovered" if succeeds else "failed"
        assert len(messages) == 1 and outcome in messages[0]
