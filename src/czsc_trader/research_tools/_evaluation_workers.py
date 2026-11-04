"""Private spawn transport; only the parent owns formal context and evidence."""

import copyreg
from io import BytesIO
import pickle
from types import MappingProxyType





def _mapping(value):
    return MappingProxyType(value)


def _reduce_mapping(value):
    return _mapping, (dict(value),)


def pack(value):
    """Serialize immutable mappings without changing global pickle behavior."""
    buffer = BytesIO()
    pickler = pickle.Pickler(buffer, protocol=pickle.HIGHEST_PROTOCOL)
    pickler.dispatch_table = {**copyreg.dispatch_table, MappingProxyType: _reduce_mapping}
    pickler.dump(value)
    return buffer.getvalue()
