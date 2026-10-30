"""Run-scoped source descriptors; verify source bytes on every step.

Only authenticated code objects are cached. Modules and their globals are fresh
for every invocation. Metadata never substitutes for a source-content check.
"""
from contextvars import ContextVar
from hashlib import sha256
import importlib.abc
import importlib.machinery
import importlib.util
import os
import stat
import sys
import types
from uuid import uuid4


_active = ContextVar('equity_source_invocation', default=None)


def _signature(value):
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode), getattr(value, 'st_file_attributes', 0) & 0x400


class BoundEquityInvocation:
    """An explicit per-run resource scope, never part of candidate identity."""

    def __init__(self, candidate):
        self.candidate = candidate
        self.token = None
        self.files = {}
        self.directories = {}
        self.codes = {}
        self.checks = 0
        self.bytes_read = 0
        self.module_base = frozenset(sys.modules)

    def _bind(self):
        from .equity_definition import _read_equity_sources, _compiled_equity_source
        digest, sources = _read_equity_sources(self.candidate.source_root, self.candidate.definition.source_files)
        if digest != self.candidate.definition.source_sha256:
            raise ValueError('equity source closure changed during execution')
        self.files, self.directories, self.codes = {}, {}, {}
        for name, content in sources.items():
            path = self.candidate.source_root / name
            current = os.stat(path, follow_symlinks=False)
            if stat.S_ISLNK(current.st_mode) or _signature(current)[3]:
                raise ValueError('equity source cannot be a filesystem link')
            self.files[name] = (str(path), len(content), _signature(current))
            self.codes[name] = _compiled_equity_source(content, str(path))
            for parent in path.parents:
                key = str(parent)
                value = os.stat(key, follow_symlinks=False)
                if stat.S_ISLNK(value.st_mode) or _signature(value)[3]:
                    raise ValueError('equity source directory became a filesystem link')
                self.directories[key] = _signature(value)
                if parent == self.candidate.source_root:
                    break

    def __enter__(self):
        self._bind()
        self.token = _active.set(self)
        return self

    def __exit__(self, *exc):
        if self.token is not None:
            _active.reset(self.token)

    def __reduce__(self):
        raise TypeError('bound source readers cannot cross process boundaries')

    def _check(self):
        self.checks += 1
        try:
            changed = False
            for path, signature in self.directories.items():
                value = os.stat(path, follow_symlinks=False)
                if stat.S_ISLNK(value.st_mode) or _signature(value)[3]:
                    raise ValueError('equity source directory became a filesystem link')
                changed |= _signature(value) != signature
            for path, _, signature in self.files.values():
                value = os.stat(path, follow_symlinks=False)
                if stat.S_ISLNK(value.st_mode) or _signature(value)[3]:
                    raise ValueError('equity source became a filesystem link')
                changed |= _signature(value) != signature
            if changed:
                self._bind()
            digest = sha256()
            for name, (path, size, signature) in self.files.items():
                with open(path, 'rb', buffering=0) as handle:
                    if _signature(os.fstat(handle.fileno())) != signature:
                        raise ValueError('equity source identity changed while opening')
                    content = handle.read(size + 1)
                self.bytes_read += len(content)
                if len(content) != size:
                    raise ValueError('equity source closure changed during execution')
                digest.update(name.encode())
                digest.update(b'\0')
                digest.update(content)
                digest.update(b'\0')
            if digest.hexdigest() != self.candidate.definition.source_sha256:
                raise ValueError('equity source closure changed during execution')
        except OSError as exc:
            raise ValueError('equity source disappeared or changed during execution') from exc

    def invoke(self, context, state):
        self._check()
        namespace = '_equity_' + uuid4().hex
        prefix = namespace + '.'
        root = self.candidate.source_root
        package = types.ModuleType(namespace)
        package.__path__ = [str(root)]
        sys.modules[namespace] = package
        module_name, function = self.candidate.definition.entrypoint.split(':')
        manifest, codes = self.files, self.codes

        class SourceLoader(importlib.machinery.SourceFileLoader):
            def __init__(self, fullname, relative):
                self.relative = relative
                super().__init__(fullname, str(root / relative))

            def get_code(self, fullname):
                return codes[self.relative]

        class SourceFinder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if not fullname.startswith(prefix):
                    return None
                relative = fullname[len(prefix):].replace('.', '/')
                package_name = relative + '/__init__.py'
                name = package_name if package_name in manifest else relative + '.py'
                if name not in manifest:
                    raise ImportError('import absent from equity source manifest')
                return importlib.util.spec_from_file_location(fullname, root / name,
                    loader=SourceLoader(fullname, name),
                    submodule_search_locations=[str(root / relative)] if name == package_name else None)

        finder = SourceFinder()
        sys.meta_path.insert(0, finder)
        try:
            relative = module_name.replace('.', '/') + '.py'
            if len(codes) == 1 and '.' not in module_name:
                # Same fresh module attributes and globals, without resolving an
                # already authenticated single-file manifest via import search.
                fullname = prefix + module_name
                spec = importlib.util.spec_from_file_location(fullname, root / relative,
                    loader=SourceLoader(fullname, relative))
                module = importlib.util.module_from_spec(spec)
                sys.modules[fullname] = module
                setattr(package, module_name, module)
                exec(codes[relative], module.__dict__)
            else:
                from importlib import import_module
                module = import_module(prefix + module_name)
            return getattr(module, function)(context, state)
        finally:
            sys.meta_path.remove(finder)
            # A fresh UUID namespace cannot belong to the pre-run module set.
            # Compute the key difference in C; still remove arbitrary namespace
            # registrations made by user code, not only imports seen by finder.
            for name in sys.modules.keys() - self.module_base:
                if name == namespace or name.startswith(prefix):
                    del sys.modules[name]


def active_invocation(candidate):
    bound = _active.get()
    return bound if bound is not None and bound.candidate is candidate else None
