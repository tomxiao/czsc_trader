"""Account-facing identity of an already prepared host input document.

The channel stores the document but does not interpret data requests or fetch data.
The host validates its preparation schema before passing it to account maintenance.
"""
from dataclasses import dataclass
import json
import math
import re

from ..instruments import InstrumentId


@dataclass(frozen=True, slots=True)
class AccountInputIdentity:
    release_hash: str
    instrument: InstrumentId
    specification_hash: str
    fee_rate: float
    document: bytes

    def __post_init__(self):
        if any(type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None
               for value in (self.release_hash, self.specification_hash)):
            raise ValueError('account input identity requires release and specification hashes')
        if type(self.instrument) is not InstrumentId:
            raise TypeError('account input identity requires an execution instrument')
        if type(self.fee_rate) not in (float, int) or not math.isfinite(self.fee_rate) or not 0 <= self.fee_rate < 1:
            raise ValueError('account input identity requires a finite model fee')
        if type(self.document) is not bytes:
            raise TypeError('account input document requires immutable bytes')
        document = json.loads(self.document)
        if type(document) is not dict:
            raise ValueError('account input document requires a JSON object')
        json.dumps(document, allow_nan=False)

    def to_dict(self):
        return json.loads(self.document)
