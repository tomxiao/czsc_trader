from pathlib import Path
from hashlib import sha256
from importlib.metadata import version
import sys, types, json
import pandas as pd
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT=Path(__file__).resolve().parents[5]
W=Path(__file__).resolve().parents[1]
OUT=W/'others'


def save(name,value):
    (OUT/name).write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def main():
    module_name='futu.common.ft_logger'
    logger_file=ROOT/'.venv/Lib/site-packages/futu/common/ft_logger.py'
    code=logger_file.read_text(encoding='utf-8');marker='__LogPathName__ = "com.futunn.FutuOpenD/Log"'
    assert code.count(marker)==1
    module=types.ModuleType(module_name);module.__file__=str(logger_file);module.__package__='futu.common'
    sys.modules[module_name]=module
    exec(compile(code.replace(marker,'__LogPathName__ = '+repr(str(ROOT/'.tmp/s018-futu-logs'))),str(logger_file),'exec'),module.__dict__)
    import futu as ft
    ft.SysConfig.enable_console_log(False);ft.SysConfig.set_all_thread_daemon(True)
    q=ft.OpenQuoteContext(host='127.0.0.1',port=11111,is_async_connect=True)
    q.set_sync_query_connect_timeout(15)
    summary={'futu_version':version('futu-api'),'scope':['US.MU','US.SOXX'],'start':'2022-01-03','end':'2026-10-30','requests':[]}
    try:
        for symbol in ['US.MU','US.SOXX']:
            ret,frame=q.get_rehab(symbol)
            if ret!=0:raise RuntimeError(f'{symbol} get_rehab failed: {frame}')
            frame=frame[frame.ex_div_date<='2026-10-30'].copy()
            save(f'analysis_{symbol[3:]}_rehab.json',json.loads(frame.to_json(orient='records',date_format='iso',double_precision=15)))
            summary['requests'].append({'symbol':symbol,'product':'rehab','rows':len(frame)})
            for adjustment in ([ft.AuType.HFQ] if symbol=='US.MU' else [ft.AuType.NONE,ft.AuType.HFQ]):
                pages=[];key=None
                for page in range(4):
                    ret,part,key=q.request_history_kline(symbol,start='2022-01-03',end='2026-10-30',
                        ktype=ft.KLType.K_DAY,autype=adjustment,max_count=1000,page_req_key=key,extended_time=False)
                    if ret!=0:raise RuntimeError(f'{symbol} {adjustment} history failed: {part}')
                    pages.append(part)
                    if key is None:break
                if key is not None:raise RuntimeError('Incomplete pagination')
                frame=pd.concat(pages,ignore_index=True).sort_values('time_key')
                assert not frame.time_key.duplicated().any()
                name=f'analysis_{symbol[3:]}_{adjustment.lower()}.json'
                save(name,json.loads(frame.to_json(orient='records',date_format='iso',double_precision=15)))
                summary['requests'].append({'symbol':symbol,'product':'daily','adjustment':adjustment,'rows':len(frame),
                    'pages':len(pages),'first':frame.time_key.min(),'last':frame.time_key.max(),'sha256':sha256((OUT/name).read_bytes()).hexdigest()})
                print(symbol,adjustment,len(frame),flush=True)
        family=ROOT/'research/S018'
        ref=json.loads((family/'experiments/EX025_20261104/others/results.json').read_text(encoding='utf-8'))['accounts']['C6300']['account_ref']
        p=family/'assets/evidence'/ref['experiment']['experiment_id']/ref['evidence_id'];raw=p.read_bytes()
        assert sha256(raw).hexdigest()==ref['sha256']
        view=materialize_equity(raw,lambda x:(p.parent/(x['sha256']+'.json')).read_bytes()).payload
        save('analysis_MU_frozen_raw.json',view['audit_inputs']['bars'])
        summary['frozen_mu_evidence']=ref
        summary['status']='FETCHED_NOT_YET_CERTIFIED'
        save('analysis_acquisition.json',summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    except Exception as exc:
        summary['status']='FAILED';summary['error']=str(exc);save('analysis_acquisition.json',summary)
        raise
    finally:q.close()


if __name__=='__main__':main()
