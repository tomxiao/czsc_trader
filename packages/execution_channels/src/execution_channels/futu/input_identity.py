"""Account-facing identity of an already prepared host input document.

The channel stores the document but does not interpret data requests or fetch data.
The host validates its preparation schema before passing it to account maintenance.
"""
from dataclasses import dataclass
import json
import math
import re

from ..instruments import InstrumentId, MarketId, AssetClass


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

    @classmethod
    def from_dict(cls, value):
        if (type(value) is not dict or set(value) != {'schema_version', 'release_hash', 'binding', 'fee_rate'}
                or value['schema_version'] != 2 or type(value['binding']) is not dict):
            raise ValueError('unsupported account input document')
        binding = value['binding']
        raw = dict(binding['instrument'])
        raw['market'], raw['asset_class'] = MarketId(raw['market']), AssetClass(raw['asset_class'])
        return cls(value['release_hash'], InstrumentId(**raw), binding['specification_hash'], value['fee_rate'],
                   json.dumps(value, sort_keys=True, allow_nan=False).encode())

    def to_dict(self):
        return json.loads(self.document)
