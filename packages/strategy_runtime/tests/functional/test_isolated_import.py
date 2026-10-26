"""Authenticated closure imports must leave their source directory unchanged."""

from importlib import import_module
from importlib.util import cache_from_source
from pathlib import Path
import sys

import pytest

from strategy_runtime import implementation_sha256
from strategy_runtime.isolated_import import load_closure_module


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def _load(root, leaf):
    files = tuple(sorted(_files(root)))
    return load_closure_module(
        f'strategy_runtime.strategies.{leaf}', source_root=root,
        source_files=files, source_sha256=implementation_sha256(files, source_root=root),
        marker='bytecode_test',
    )


@pytest.mark.parametrize('disabled', [False, True])
@pytest.mark.parametrize('redirected', [False, True])
def test_eager_and_delayed_imports_preserve_source_and_global_cache_policy(tmp_path, monkeypatch, disabled, redirected):
    root = tmp_path / 'source'
    package = root / 'strategies'
    nested = package / 'explanation'
    nested.mkdir(parents=True)
    (package / '__init__.py').write_text('from .eager import VALUE\n', encoding='utf-8')
    (package / 'eager.py').write_text('VALUE = 7\n', encoding='utf-8')
    (package / 'cache_fixture.py').write_text(
        'import sys\n'
        'initial_policy = sys.dont_write_bytecode\n'
        'def explain():\n'
        '    from .explanation import explain\n'
        '    return explain()\n', encoding='utf-8',
    )
    (nested / '__init__.py').write_text(
        'def explain():\n'
        '    from .value import VALUE\n'
        '    return VALUE\n', encoding='utf-8',
    )
    (nested / 'value.py').write_text('from ..eager import VALUE\n', encoding='utf-8')
    before = _files(root)
    cache = tmp_path / 'cache'
    monkeypatch.setattr(sys, 'pycache_prefix', str(cache) if redirected else None)
    monkeypatch.setattr(sys, 'dont_write_bytecode', disabled)
    module = _load(root, 'cache_fixture')
    assert module.initial_policy is disabled
    assert sys.dont_write_bytecode is disabled
    assert _files(root) == before
    assert _files(cache) == {}
    assert module.explain() == module.explain() == 7
    assert _load(root, 'cache_fixture') is module
    assert sys.dont_write_bytecode is disabled
    assert _files(root) == before
    assert _files(cache) == {}

    # Unrelated modules still follow the caller's cache policy.
    (tmp_path / 'ordinary_cache_fixture.py').write_text('VALUE = 11\n', encoding='utf-8')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, 'ordinary_cache_fixture', raising=False)
    assert import_module('ordinary_cache_fixture').VALUE == 11
    assert Path(cache_from_source(str(tmp_path / 'ordinary_cache_fixture.py'))).exists() is not disabled


@pytest.mark.parametrize('failure', ['entry', 'delayed'])
def test_failed_imports_preserve_source_and_do_not_suppress_exceptions(tmp_path, monkeypatch, failure):
    root = tmp_path / 'source'
    package = root / 'strategies'
    package.mkdir(parents=True)
    (package / 'broken.py').write_text('raise RuntimeError("fixture failure")\n', encoding='utf-8')
    (package / 'failure_fixture.py').write_text(
        'from . import broken\n' if failure == 'entry' else
        'def explain():\n    from . import broken\n', encoding='utf-8',
    )
    before = _files(root)
    monkeypatch.setattr(sys, 'pycache_prefix', None)
    monkeypatch.setattr(sys, 'dont_write_bytecode', False)
    with pytest.raises(RuntimeError, match='fixture failure'):
        module = _load(root, 'failure_fixture')
        if failure == 'delayed':
            module.explain()
    assert sys.dont_write_bytecode is False
    assert _files(root) == before
