"""Session-owned binary transport for shared, immutable account inputs.

Only the parent creates these anonymous shared-memory blocks. Workers decode a
block once, cache at most eight inputs, and never publish or modify its bytes.
Blocks live until the corresponding batch has finished or the pool is closed.
"""
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from multiprocessing.shared_memory import SharedMemory
import pickle


@dataclass(frozen=True, slots=True)
class AccountInputRef:
    name: str
    size: int
    sha256: str


class AccountInputStore:
    def __init__(self):
        self.blocks = {}
        self.closed = False

    def retain(self, keys):
        if self.closed:
            raise RuntimeError('account input transport is closed')
        if len(keys) > 8:
            raise ValueError('account input transport supports at most eight shared inputs per batch')
        for key in tuple(self.blocks):
            if key not in keys:
                block, _ = self.blocks.pop(key)
                block.close()
                block.unlink()

    def put(self, key, value):
        if self.closed:
            raise RuntimeError('account input transport is closed')
        if key in self.blocks:
            return self.blocks[key][1]
        if len(self.blocks) >= 8:
            raise ValueError('account input transport capacity exceeded')
        content = pickle.dumps(value, protocol=5)
        block = SharedMemory(create=True, size=len(content))
        try:
            block.buf[:len(content)] = content
            reference = AccountInputRef(block.name, len(content), sha256(content).hexdigest())
            self.blocks[key] = block, reference
            return reference
        except BaseException:
            block.close()
            block.unlink()
            raise

    def close(self):
        if self.closed:
            return
        self.retain(())
        self.closed = True


_worker_inputs = OrderedDict()


def read_account_input(reference):
    if type(reference) is not AccountInputRef:
        raise TypeError('account input transport requires an owned reference')
    if reference in _worker_inputs:
        _worker_inputs.move_to_end(reference)
        return _worker_inputs[reference]
    block = SharedMemory(name=reference.name, create=False)
    try:
        if reference.size <= 0 or reference.size > block.size:
            raise ValueError('account input shared block size differs')
        content = block.buf[:reference.size]
        try:
            if sha256(content).hexdigest() != reference.sha256:
                raise ValueError('account input shared block digest differs')
            value = pickle.loads(content)
        finally:
            content.release()
    finally:
        block.close()
    _worker_inputs[reference] = value
    while len(_worker_inputs) > 8:
        _worker_inputs.popitem(last=False)
    return value
