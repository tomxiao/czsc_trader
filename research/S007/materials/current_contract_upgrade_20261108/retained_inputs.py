"""Read retained DFLS products by their published preparation and content identities."""
from datetime import date
import json
from pathlib import Path
from uuid import UUID

from czsc_trader.research_tools import EvidenceRef
from dataflows import (AssetClass, BarFrequency, Dataflows, DataSpace, EquityDataRequest,
    EquityProduct, EquityQuery, EquitySession, InstrumentId, MarketId, PreparedDataRef,
    PriceAdjustment, ProviderConfig, SourceRef)
from strategy_runtime.dataset_observations import DatasetObservationBinding

ROOT = Path(__file__).resolve().parents[4]


def load():
    ref_path = ROOT / 'research/S007/experiments/EX007_20261106/others/account_ref_C9960.json'
    reference = EvidenceRef.from_dict(json.loads(ref_path.read_bytes()))
    # This is immutable RAW-era evidence, read only for its historical data identities.
    # It is deliberately not admitted as a current HFQ account/economic result.
    document = json.loads(reference.resolve(ROOT).read_bytes())
    binding = document['request']['input_binding']
    prepared = binding['prepared']
    prepared = PreparedDataRef(UUID(prepared['space_id']), UUID(prepared['preparation_id']), prepared['manifest_sha256'])
    data = Dataflows(base_dir=ROOT, space=DataSpace(Path('research/S007/assets/data')),
                    providers=ProviderConfig(bindings={}, equity_bindings={}))
    identities = dict(binding['content_identities'])
    for item in binding['auxiliary_inputs']:
        identities['auxiliary:' + item['input']['name'] + ':bars'] = item['bars_sha256']
    frames, facts = {}, {}
    for role, value in binding['request_bindings']:
        if role not in ('bars', 'sessions', 'auxiliary:adjusted_daily:bars'):
            continue
        inst, query = value['instrument'], dict(value['query'])
        for key, cls in (('product', EquityProduct), ('frequency', BarFrequency),
                         ('adjustment', PriceAdjustment), ('session', EquitySession)):
            query[key] = cls(query[key])
        query.update(start=date.fromisoformat(query['start']), end=date.fromisoformat(query['end']))
        request = EquityDataRequest(InstrumentId(MarketId(inst['market']), AssetClass(inst['asset_class']), inst['symbol']),
                                   SourceRef(**value['source']), EquityQuery(**query))
        result = data.fetch(request, prepared=prepared)
        if not result.ready or result.identity.content_sha256 != identities[role]:
            raise ValueError(f'retained {role} differs from published identity')
        name = {'bars': 'raw_daily', 'sessions': 'sessions', 'auxiliary:adjusted_daily:bars': 'hfq_daily'}[role]
        frames[name] = result.dataframe.copy(deep=True)
        facts[name] = {'content_sha256': result.identity.content_sha256,
                       'metadata': dict(result.identity.metadata), 'request': value}
    for value in binding['observation_bindings']:
        item = DatasetObservationBinding.from_dict(value)
        if item.request is None:
            continue
        result = data.fetch(item.request, prepared=prepared)
        if not result.ready or result.identity.content_sha256 != item.content_sha256:
            raise ValueError(f'retained {item.input.name} differs from published identity')
        frames[item.input.name] = result.dataframe.copy(deep=True)
        facts[item.input.name] = {'content_sha256': result.identity.content_sha256,
            'metadata': dict(result.identity.metadata), 'binding': value}
    return frames, {'reference': reference.to_dict(), 'prepared': binding['prepared'], 'inputs': facts}


if __name__ == '__main__':
    frames, provenance = load()
    print(json.dumps({'rows': {name: len(frame) for name, frame in frames.items()},
                      'prepared': provenance['prepared']}, ensure_ascii=False))
