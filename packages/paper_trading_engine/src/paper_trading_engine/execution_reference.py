"""PTE-owned, authenticated RAW prices supplied exclusively to execution channels."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import re
from uuid import UUID

from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct,
    EquityQuery, EquitySession, InstrumentId, MarketId, PreparedDataRef,
    PriceAdjustment, SourceRef)
from dataflows.equity_contracts import EquityParameters


@dataclass(frozen=True, slots=True)
class ExecutionReferenceBinding:
    parameters: EquityParameters
    prepared: PreparedDataRef
    content_sha256: str

    def __post_init__(self):
        if type(self.parameters) is not EquityParameters or type(self.prepared) is not PreparedDataRef:
            raise TypeError('execution reference requires typed DFLS request and preparation')
        if (self.parameters.query.product is not EquityProduct.BARS
                or self.parameters.query.adjustment is not PriceAdjustment.NONE):
            raise ValueError('simulated execution requires an independent RAW price publication')
        if re.fullmatch('[0-9a-f]{64}', self.content_sha256) is None:
            raise ValueError('execution reference requires a content identity')

    @property
    def request(self):
        p = self.parameters
        return EquityDataRequest(p.instrument, p.source, p.query)

    def to_dict(self):
        value = asdict(self)
        for key in ('start', 'end'):
            value['parameters']['query'][key] = value['parameters']['query'][key].isoformat()
        for key in ('space_id', 'preparation_id'):
            value['prepared'][key] = str(value['prepared'][key])
        return value

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {'parameters', 'prepared', 'content_sha256'}:
            raise ValueError('invalid execution reference binding')
        p = value['parameters']
        instrument = {**p['instrument'], 'market': MarketId(p['instrument']['market']),
                      'asset_class': AssetClass(p['instrument']['asset_class'])}
        query = dict(p['query'])
        for key, enum in (('product', EquityProduct), ('frequency', BarFrequency),
                          ('adjustment', PriceAdjustment), ('session', EquitySession)):
            query[key] = enum(query[key])
        for key in ('start', 'end'):
            query[key] = date.fromisoformat(query[key])
        prepared = dict(value['prepared'])
        for key in ('space_id', 'preparation_id'):
            prepared[key] = UUID(prepared[key])
        return cls(EquityParameters(InstrumentId(**instrument), SourceRef(**p['source']), EquityQuery(**query)),
                   PreparedDataRef(**prepared), value['content_sha256'])

    def fetch(self, dataflows, interval, *, latency_seconds):
        result = dataflows.fetch(self.request, prepared=self.prepared)
        if not result.ready or result.identity.content_sha256 != self.content_sha256:
            raise ValueError('execution RAW publication is unavailable or changed')
        if type(latency_seconds) is not int or latency_seconds < 0:
            raise ValueError('execution reference latency must be a nonnegative integer')
        frame = result.dataframe
        cutoff = interval.start - timedelta(seconds=latency_seconds)
        history = frame.loc[(frame.Date <= cutoff) & (frame.AvailableDate <= interval.start)]
        if history.empty:
            raise ValueError('no completed RAW execution reference is available at the decision')
        if not history.Date.is_monotonic_increasing or history.Date.duplicated().any():
            raise ValueError('execution reference observations must be ordered and unique')
        row = history.iloc[-1]
        stamp = row.Date.to_pydatetime() if hasattr(row.Date, 'to_pydatetime') else row.Date
        return PreparedExecutionReference(Decimal(str(row.Close)), stamp, self.content_sha256)


@dataclass(frozen=True, slots=True)
class PreparedExecutionReference:
    price: Decimal
    observed_through: datetime
    content_sha256: str

    def __post_init__(self):
        if type(self.price) is not Decimal or not self.price.is_finite() or self.price <= 0:
            raise ValueError('execution price must be finite and positive')
        if type(self.observed_through) is not datetime or self.observed_through.utcoffset() is None:
            raise ValueError('execution reference requires an aware observation time')
        if re.fullmatch('[0-9a-f]{64}', self.content_sha256) is None:
            raise ValueError('execution reference requires a content identity')

    def to_dict(self):
        return {'price': str(self.price), 'observed_through': self.observed_through.isoformat(),
                'content_sha256': self.content_sha256}
