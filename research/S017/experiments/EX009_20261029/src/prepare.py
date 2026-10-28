"""Public DFLS audit of authorized auxiliary prices; no strategy evaluations."""
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
import json
import os
from zoneinfo import ZoneInfo

from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct,
    EquityQuery, InstrumentId, MarketId, PreparePolicy, ProviderConfig, SourceRef,
    UsEquityBarPolicy, TimeInterval, futu_equity_bindings)
from strategy_runtime import (ResearchExecutionSpec, UsEquitySpec, AccountPolicy,
    CashAvailabilityPolicy, ExecutionResources)
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SOURCE = SourceRef('futu', 's017-auxiliary-rth-raw-v1-20261029')
MAIN_SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
START, END = date(2018,11,1), date(2025,12,31)
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)


def requests():
    primary = tuple(EquityDataRequest(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'), MAIN_SOURCE,
        EquityQuery(product, START, END, BarFrequency.M30)) for product in EquityProduct)
    auxiliary = tuple(EquityDataRequest(InstrumentId(MarketId.US, AssetClass.ETF, symbol), SOURCE,
        EquityQuery(product, START, END, frequency))
        for symbol, frequency in (('SPY', BarFrequency.DAILY), ('QQQ', BarFrequency.DAILY),
            ('XLK', BarFrequency.DAILY), ('SPY', BarFrequency.M30), ('XLK', BarFrequency.M30))
        for product in (EquityProduct.BARS, EquityProduct.SESSIONS))
    return primary + auxiliary


def main():
    scratch = ROOT/'.tmp/s017-auxiliary-data'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ['APPDATA'] = str(scratch/'sdk-logs')
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    import futu
    quotes = futu.OpenQuoteContext(host='127.0.0.1', port=11111, is_async_connect=True)
    quotes.set_sync_query_connect_timeout(8)
    output = {'observed_at': datetime.now(timezone.utc).isoformat(), 'scope': [str(START), str(END)],
        'source': asdict(SOURCE), 'strategy_evaluations': 0, 'reserved_price_accessed': False,
        'availability_basis': 'BAR_CLOSE_RESEARCH_ASSUMPTION; historical publication time unverified'}
    try:
        prior = json.loads((ROOT/'research/S017/materials/pre_registration_readiness.json').read_text(encoding='utf-8'))
        zone = ZoneInfo('America/New_York')
        intervals = tuple(TimeInterval(datetime.fromisoformat(item['start_et']).replace(tzinfo=zone),
            datetime.fromisoformat(item['resume_et']).replace(tzinfo=zone)) for item in prior['known_events'])
        bindings = futu_equity_bindings(source=MAIN_SOURCE, quote_context=quotes,
                                      research_policy=UsEquityBarPolicy(1, .01, intervals))
        bindings.update(futu_equity_bindings(source=SOURCE, quote_context=quotes,
                                            research_policy=UsEquityBarPolicy(1, .01)))
        context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S017'),
            providers=ProviderConfig(bindings={}, equity_bindings=bindings),
            execution_spec=SPEC, resources=ExecutionResources(max_workers=4, native_threads_per_worker=1, random_seed=17))
        planned = requests()
        print('PREPARING 14 exact products; three ETFs, two frequencies, existing LITE retained', flush=True)
        prepared = context.data.prepare(planned, policy=PreparePolicy.REUSE)
        output['status'] = prepared.status.value
        output['items'] = [{'request': asdict(item.request), 'status': item.status.value,
                            'error': None if item.error is None else str(item.error)} for item in prepared.items]
        if not prepared.ready:
            raise RuntimeError('Auxiliary preparation did not return READY')
        output['reference'] = asdict(prepared.reference)
        output['products'] = []
        old = json.loads((ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json').read_text(encoding='utf-8'))
        retained = {item['product']:item['sha256'] for item in old['items']}
        frames = {}
        for query in planned:
            item = context.data.fetch(query, prepared=prepared.reference)
            if not item.ready:
                raise RuntimeError(str(item.error))
            frame = item.dataframe
            instrument, spec = query.parameters.instrument, query.parameters.query
            if instrument.symbol == 'LITE' and item.identity.content_sha256 != retained[spec.product.value]:
                raise ValueError('Original LITE product identity changed; comparisons must stop')
            key = f'{instrument.symbol}:{spec.frequency.value}:{spec.product.name}'
            frames[key] = frame
            row = {'key':key, 'rows':len(frame), 'sha256':item.identity.content_sha256,
                'metadata':{k:v for k,v in item.identity.metadata.items() if k!='sessions'},
                'sessions':len(item.identity.metadata['sessions']),
                'first':frame.Date.min().isoformat(), 'last':frame.Date.max().isoformat()}
            if spec.product is EquityProduct.BARS:
                row['statuses'] = frame.BarStatus.value_counts().to_dict()
                if instrument.symbol != 'LITE' and row['statuses'] != {'OBSERVED':len(frame)}:
                    raise RuntimeError(f'Auxiliary coverage requires review: {key} {row["statuses"]}')
                if instrument.symbol != 'LITE' and spec.frequency is BarFrequency.DAILY:
                    ratio = frame.Close / frame.Close.shift(1)
                    row['large_price_discontinuities'] = [
                        {'date':frame.Date.iloc[i].isoformat(), 'close_ratio':float(ratio.iloc[i])}
                        for i in range(1,len(frame)) if ratio.iloc[i] < .7 or ratio.iloc[i] > 1.4]
            assert frame.Date.dt.tz_convert('America/New_York').max().date() <= END
            output['products'].append(row)
            print(key, len(frame), 'READY', flush=True)
        output['daily_rth_comparison'] = {}
        for symbol in ('SPY','XLK'):
            daily = frames[f'{symbol}:{BarFrequency.DAILY.value}:BARS'].copy()
            intraday = frames[f'{symbol}:{BarFrequency.M30.value}:BARS'].copy()
            daily.index = daily.Date.dt.tz_convert('America/New_York').dt.date
            intraday['_day'] = intraday.Date.dt.tz_convert('America/New_York').dt.date
            aggregate = intraday.groupby('_day').agg(Open=('Open','first'), High=('High','max'),
                Low=('Low','min'), Close=('Close','last'))
            diff = (daily.loc[aggregate.index, aggregate.columns] - aggregate).abs()
            output['daily_rth_comparison'][symbol] = {'max_absolute_price_difference':diff.max().to_dict(),
                'sessions_differing_more_than_one_cent':int(diff.gt(.010001).any(axis=1).sum())}
        output['research_gate'] = 'READY_WITH_EXPLICIT_RAW_PRICE_AND_AVAILABILITY_ASSUMPTIONS'
    except Exception as exc:
        output['research_gate'] = 'NOT_PASSED'
        output['error'] = str(exc)
        raise
    finally:
        quotes.close()
        (WORK/'others/data_readiness.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'status':output.get('status'),'gate':output.get('research_gate'),'error':output.get('error')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
