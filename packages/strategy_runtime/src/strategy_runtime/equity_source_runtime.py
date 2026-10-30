"""Load one isolated strategy module per account and retain it for the replay."""
from contextvars import ContextVar
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from uuid import uuid4


_active = ContextVar('equity_source_invocation', default=None)


class BoundEquityInvocation:
    """One account owns a module namespace and an in-memory source snapshot."""

    def __init__(self, candidate):
        self.candidate = candidate
        self.token = None
        self.namespace = '_equity_' + uuid4().hex
        self.prefix = self.namespace + '.'
        self.finder = None
        self.function = None
        self.checks = 0
        self.bytes_read = 0
        self.loads = 0
        self.entered = False

    def __enter__(self):
        if self.entered:
            raise RuntimeError('strategy module scope cannot be entered twice')
        self.entered = True
        try:
            self._load()
            self.token = _active.set(self)
            return self
        except BaseException:
            self._cleanup()
            raise

    def __exit__(self, *exc):
        if self.token is not None:
            _active.reset(self.token)
            self.token = None
        self._cleanup()

    def __reduce__(self):
        raise TypeError('loaded strategy modules cannot cross process boundaries')

    def _load(self):
        from .equity_definition import _compiled_equity_source
        root = self.candidate.source_root
        codes = {}
        # Read the complete declared closure once, including lazy relative
        # imports. Later decisions and imports never reopen these source files.
        for relative in self.candidate.definition.source_files:
            path = root / relative
            content = path.read_bytes()
            self.bytes_read += len(content)
            codes[relative] = _compiled_equity_source(content, str(path))
        prefix = self.prefix

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
                name = package_name if package_name in codes else relative + '.py'
                if name not in codes:
                    raise ImportError('import absent from equity source manifest')
                return importlib.util.spec_from_file_location(fullname, root / name,
                    loader=SourceLoader(fullname, name),
                    submodule_search_locations=[str(root / relative)] if name == package_name else None)

        package = types.ModuleType(self.namespace)
        package.__path__ = [str(root)]
        sys.modules[self.namespace] = package
        self.finder = SourceFinder()
        sys.meta_path.insert(0, self.finder)
        module_name, function_name = self.candidate.definition.entrypoint.split(':')
        from importlib import import_module
        module = import_module(prefix + module_name)
        function = getattr(module, function_name)
        if not callable(function):
            raise TypeError('equity strategy entrypoint must be callable')
        self.function = function
        self.loads = 1

    def invoke(self, context, state):
        if self.function is None:
            raise RuntimeError('strategy module scope is not active')
        return self.function(context, state)

    def _cleanup(self):
        self.function = None
        if self.finder is not None:
            sys.meta_path.remove(self.finder)
            self.finder = None
        # Include module registrations made directly by strategy code, not only
        # imports seen by the finder. Cleanup happens once per account.
        for name in tuple(sys.modules):
            if name == self.namespace or name.startswith(self.prefix):
                del sys.modules[name]


def active_invocation(candidate):
    bound = _active.get()
    return bound if bound is not None and bound.candidate is candidate else None
