from pathlib import Path
from datetime import date
from dataclasses import asdict
import json,sys,types
from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext,create_research_context
from dataflows import (AssetClass,BarFrequency,EquityDataRequest,EquityProduct,EquityQuery,
    InstrumentId,MarketId,PreparePolicy,ProviderConfig,PriceAdjustment,SourceRef,UsEquityBarPolicy,futu_equity_bindings)
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import execution_spec_from_dict

ROOT=Path(__file__).resolve().parents[5];W=Path(__file__).resolve().parents[1]


def main():
    name='futu.common.ft_logger';p=ROOT/'.venv/Lib/site-packages/futu/common/ft_logger.py'
    code=p.read_text(encoding='utf-8');marker='__LogPathName__ = "com.futunn.FutuOpenD/Log"';assert code.count(marker)==1
    mod=types.ModuleType(name);mod.__file__=str(p);mod.__package__='futu.common';sys.modules[name]=mod
    exec(compile(code.replace(marker,'__LogPathName__ = '+repr(str(ROOT/'.tmp/s018-futu-logs'))),str(p),'exec'),mod.__dict__)
    import futu as ft
    ft.SysConfig.enable_console_log(False);ft.SysConfig.set_all_thread_daemon(True)
    q=ft.OpenQuoteContext(host='127.0.0.1',port=11111,is_async_connect=True);q.set_sync_query_connect_timeout(15)
    source=SourceRef('futu','s018-mu-soxx-hfq-research-20261104-v1')
    raw=json.loads((ROOT/'research/S018/experiments/EX025_20261104/others/results.json').read_text(encoding='utf-8'))
    spec=execution_spec_from_dict(raw['accounts']['C6300']['definition']['execution_spec'])
    try:
        bindings=futu_equity_bindings(source=source,quote_context=q,maximum_pages=3,research_policy=UsEquityBarPolicy(1,.01))
        ctx=create_research_context(RepositoryContext.discover(ROOT),d.ResearchBatchRef('S018'),
            providers=ProviderConfig(bindings={},equity_bindings=bindings),execution_spec=spec,resources=ExecutionResources(1,1,17))
        requests=tuple(EquityDataRequest(InstrumentId(MarketId.US,AssetClass.STOCK if s=='MU' else AssetClass.ETF,s),source,
            EquityQuery(p,date(2022,1,3),date(2026,10,30),BarFrequency.DAILY,
                PriceAdjustment.BACKWARD if p is EquityProduct.BARS else PriceAdjustment.NONE))
            for s in ['MU','SOXX'] for p in [EquityProduct.BARS,EquityProduct.SESSIONS])
        ready=ctx.data.prepare(requests,policy=PreparePolicy.REUSE)
        out={'status':ready.status.value,'scope':'Research HFQ bars and sessions only, not a complete RAW account input',
            'source':asdict(source),'reference':asdict(ready.reference) if ready.ready else None,
            'items':[{'instrument':asdict(x.request.parameters.instrument),'product':x.request.parameters.query.product.value,
                'status':x.status.value,'error':str(x.error) if x.error else None,
                'content_sha256':x.identity.content_sha256 if x.identity else None} for x in ready.items]}
        (W/'others/analysis_df_preparation.json').write_bytes((json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n').encode())
        print(json.dumps(out,ensure_ascii=False,default=str),flush=True)
        assert ready.ready
    finally:q.close()


if __name__=='__main__':main()
