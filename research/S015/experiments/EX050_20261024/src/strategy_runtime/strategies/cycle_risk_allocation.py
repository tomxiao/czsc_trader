"""Causal price information and dated prequential coefficients, SRT V2.

Coefficients are research parameters learned outside this runtime. The runtime
calculates features from supplied market frames and never reads research files.
The 2024-12-31 canonical seed is explicitly cash-only, with no intraday features.
"""
from collections.abc import Mapping
from datetime import date
import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, DataCoverageRequirement
from strategy_runtime import (StrategyImplementationV2, StrategyDefinition, InputContract,
    InputRequirement, CutoffRule, DecisionContract, ExecutionPolicy, MonitoringPolicy,
    RequiredCapabilities, ObservationDefinition, ObservationSeries, HistoryPolicy, CalculationScope)

PRICE = ('r1', 'r5', 'vol20', 'range20')
PATH = ('return_time_balance', 'extrema_order', 'excursion_balance', 'halfday_balance')
VOL = ('range_expansion', 'prior_range_compression', 'shock_concentration', 'gap_energy_share')
COLUMNS = PRICE + ('pressure',) + PATH + VOL
TIMES = ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00')
FIRST = date(2025, 1, 2)
LAST = date(2026, 10, 21)


def _day(value):
    if not isinstance(value, str):
        raise ValueError('model dates must be ISO date strings')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('model dates must use YYYY-MM-DD')
    return parsed


def _validate_legacy_model(parameters):
    p = dict(parameters)
    if set(p) != {'family', 'mode', 'hold', 'exposure', 'schedule'}:
        raise ValueError('exact fixed prototype parameter fields required')
    if p['family'] not in ('A', 'B') or p['mode'] not in ('path', 'risk', 'and'):
        raise ValueError('unknown family or permission mode')
    if type(p['hold']) is not int or p['hold'] < 1:
        raise ValueError('hold must be a positive integer')
    if isinstance(p['exposure'], bool) or not isinstance(p['exposure'], (int, float)) or not np.isfinite(p['exposure']) or not 0 < p['exposure'] <= 1:
        raise ValueError('exposure must be finite in (0,1]')
    if not isinstance(p['schedule'], (list, tuple)):
        raise ValueError('schedule must be a sequence')
    previous = date(2024, 12, 31)
    for item in p['schedule']:
        if not isinstance(item, Mapping) or set(item) != {'date', 'train_known_max', 'models'}:
            raise ValueError('invalid scheduled model fields')
        day, known = _day(item['date']), _day(item['train_known_max'])
        if not FIRST <= day <= LAST or day <= previous or known >= day:
            raise ValueError('models must be unique ordered research dates and strictly past-trained')
        previous = day
        if not isinstance(item['models'], Mapping) or set(item['models']) != {'path', 'risk'}:
            raise ValueError('each schedule entry requires both path and risk models')
        for role, model in item['models'].items():
            fields = {'columns', 'center', 'scale', 'beta'} | ({'threshold'} if role == 'risk' else set())
            if not isinstance(model, Mapping) or set(model) != fields:
                raise ValueError('invalid coefficient fields')
            cols = model['columns']
            if not isinstance(cols, (list, tuple)) or not cols or len(cols) != len(set(cols)) or not set(cols) <= set(COLUMNS):
                raise ValueError('model columns must be unique admitted price features')
            for key, length in (('center', len(cols)), ('scale', len(cols)), ('beta', len(cols)+1)):
                value = model[key]
                if not isinstance(value, (list, tuple)) or len(value) != length or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value) or not np.isfinite(value).all():
                    raise ValueError('coefficient vector length, type or finiteness invalid')
            if (np.asarray(model['scale']) <= 0).any():
                raise ValueError('strictly positive feature scales required')
            if role == 'risk' and (isinstance(model['threshold'], bool) or not isinstance(model['threshold'], (int,float)) or not np.isfinite(model['threshold'])):
                raise ValueError('finite risk threshold required')
    return p


MODES = ('fixed100', 'fixed50', 'fixed75', 'risk_reject', 'risk_half')

def validate_parameters(parameters):
    p = dict(parameters)
    if set(p) != {'allocation_mode', 'hold', 'schedule'} or p['allocation_mode'] not in MODES:
        raise ValueError('exact fixed P2 allocation fields required')
    if type(p['hold']) is not int or p['hold'] != 3:
        raise ValueError('P2 holds the original three-day intent clock fixed')
    _validate_legacy_model({'family':'A','mode':'path','hold':3,'exposure':1.,'schedule':p['schedule']})
    return p


def _ohlc(frame, name):
    fields = ['Date', 'Open', 'High', 'Low', 'Close']
    if any(c not in frame for c in fields):
        raise ValueError(f'{name}: OHLC fields required')
    f = frame[fields].copy(); f.attrs = {}
    f['Date'] = pd.to_datetime(f.Date, errors='raise')
    if f.Date.isna().any() or f.Date.duplicated().any() or not f.Date.is_monotonic_increasing:
        raise ValueError(f'{name}: unique ordered timestamps required')
    values = f[fields[1:]].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(f'{name}: finite positive OHLC required')
    o, h, l, c = values.T
    tolerance = 1e-10 * np.maximum(h, 1.)
    if ((h+tolerance < np.maximum(o,c)) | (l-tolerance > np.minimum(o,c)) | (h < l)).any():
        raise ValueError(f'{name}: invalid OHLC bounds')
    f[fields[1:]] = values
    return f


def _ratio(a, b):
    if not np.isfinite(a) or not np.isfinite(b) or b < 0 or (b == 0 and a != 0):
        raise ValueError('invalid observed ratio operands')
    return 0. if b == 0 else float(a/b)


def causal_features(market, execution, intraday):
    adj, raw, bars = (_ohlc(f,n) for f,n in ((market,'market'),(execution,'execution'),(intraday,'intraday')))
    if not 75 <= len(adj) <= 509 or len(raw) != len(adj) or not adj.Date.equals(raw.Date):
        raise ValueError('aligned canonical daily history with 75 warmup rows required')
    if not adj.Date.eq(adj.Date.dt.normalize()).all() or adj.Date.iloc[0] != pd.Timestamp('2024-09-09') or adj.Date.iloc[74] != pd.Timestamp('2024-12-31') or adj.Date.iloc[-1] > pd.Timestamp(LAST):
        raise ValueError('unexpected research daily history')
    if any(c not in execution for c in ('Amount','Volume')):
        raise ValueError('observed raw Amount and Volume required for pressure')
    av = execution[['Amount','Volume']].to_numpy(float)
    if not np.isfinite(av).all() or (av <= 0).any():
        raise ValueError('positive finite Amount and Volume required')
    devdates = adj.Date.iloc[75:].dt.strftime('%Y-%m-%d').tolist()
    groups = list(bars.groupby(bars.Date.dt.strftime('%Y-%m-%d'),sort=False))
    if len(bars) != 8*len(devdates) or [d for d,_ in groups] != devdates:
        raise ValueError('eight intraday bars on every and only development session required')
    a = adj[['Open','High','Low','Close']].to_numpy(float)
    tr = np.empty(len(a)); tr[0]=a[0,1]-a[0,2]
    tr[1:]=np.maximum.reduce([a[1:,1]-a[1:,2],np.abs(a[1:,1]-a[:-1,3]),np.abs(a[1:,2]-a[:-1,3])])
    c=adj.Close
    daily=pd.DataFrame({'r1':c.pct_change(),'r5':c/c.shift(5)-1,'vol20':c.pct_change().rolling(20).std(ddof=1),'range20':((adj.High-adj.Low)/c).rolling(20).mean(),'pressure':raw.Close.to_numpy()/(av[:,0]/av[:,1])-1})
    rows=[{'date':'2024-12-31',**{k:0. for k in COLUMNS},'feature_ready':False}]
    for pos,(day,b) in enumerate(groups):
        if tuple(b.Date.dt.strftime('%H:%M')) != TIMES or not (b.Date.dt.second.eq(0)&b.Date.dt.microsecond.eq(0)&b.Date.dt.nanosecond.eq(0)).all():
            raise ValueError('unexpected 30-minute timestamps')
        i=pos+75; bo,bh,bl,bc=b[['Open','High','Low','Close']].to_numpy(float).T
        path=np.log(np.r_[bo[0],bc]);u=np.diff(path)
        variation=float(np.abs(u).sum());energy=float(np.square(u).sum())
        up=float(np.max(path-np.minimum.accumulate(path)));down=float(np.max(np.maximum.accumulate(path)-path))
        prior20=float(tr[i-20:i].mean());prior5=float(tr[i-5:i].mean())
        gap=float(np.log(a[i,0]/a[i-1,3]));gap2=gap*gap
        rows.append({'date':day,**daily.iloc[i].to_dict(),
            'return_time_balance':_ratio(float(np.dot(np.linspace(-1,1,8),u)),variation),
            'extrema_order':(int(np.argmax(bh))-int(np.argmin(bl)))/7,
            'excursion_balance':_ratio(up-down,variation),
            'halfday_balance':_ratio(float(u[4:].sum()-u[:4].sum()),variation),
            'range_expansion':_ratio(float(tr[i]-prior20),float(tr[i]+prior20)),
            'prior_range_compression':_ratio(prior5-prior20,prior5+prior20),
            'shock_concentration':_ratio(float(np.square(u).max()),energy),
            'gap_energy_share':_ratio(gap2,gap2+energy),'feature_ready':True})
    out=pd.DataFrame(rows).set_index('date');out.index=pd.DatetimeIndex(out.index)
    if not np.isfinite(out[list(COLUMNS)].to_numpy(float)).all():
        raise ValueError('nonfinite features')
    return out


def intentions(features, parameters):
    p=validate_parameters(parameters);age=0;index=-1;rows=[];schedule=p['schedule'];fraction=None
    for ts,row in features.iterrows():
        day=ts.date().isoformat()
        while index+1 < len(schedule) and schedule[index+1]['date'] <= day:
            index+=1
        path=risk=threshold=0.;ready=bool(row.feature_ready and index>=0)
        if ready:
            model=schedule[index]['models'];pred={}
            for role,m in model.items():
                x=(row[list(m['columns'])].to_numpy(float)-np.asarray(m['center']))/np.asarray(m['scale'])
                pred[role]=float(m['beta'][0]+x@np.asarray(m['beta'][1:]))
            path,risk=pred['path'],pred['risk'];threshold=float(model['risk']['threshold'])
            if not np.isfinite([path,risk,threshold]).all():raise ValueError('nonfinite prediction')
        risk_allowed = ready and risk <= threshold
        permitted = ready and path >= 0 and (p['allocation_mode'] != 'risk_reject' or risk_allowed)
        if age:
            age = 0 if age >= 3 else age + 1
            if not age:
                fraction = None
        elif permitted:
            age = 1
            fraction = {'fixed100':1., 'fixed50':.5, 'fixed75':.75,
                        'risk_reject':1., 'risk_half':1. if risk_allowed else .5}[p['allocation_mode']]
        rows.append({'target_position':float(age>0),'entry_allocation_fraction':fraction,
                     'intent_age':age,'path_prediction':path,'risk_prediction':risk,
                     'risk_threshold':threshold,'model_ready':float(ready),
                     'permission':float(permitted),'risk_allowed':float(risk_allowed)})
    return features.join(pd.DataFrame(rows,index=features.index))


class CycleRiskAllocation(StrategyImplementationV2):
    def __init__(self,parameters):
        p=validate_parameters(parameters.values)
        inputs=InputContract((
            InputRequirement('market',Dataset.ETF_OHLCV.value,'159326.SZ','daily',21,CutoffRule.SIGNAL_SESSION),
            InputRequirement('execution',Dataset.ETF_UNADJUSTED_DAILY.value,'159326.SZ','daily',21,CutoffRule.SIGNAL_SESSION),
            InputRequirement('intraday',Dataset.ETF_UNADJUSTED_INTRADAY.value,'159326.SZ','30m',0,CutoffRule.SIGNAL_SESSION),
            InputRequirement('calendar',Dataset.TRADING_CALENDAR.value,'SZSE','daily',0,CutoffRule.LATEST_AVAILABLE)))
        self._definition=StrategyDefinition(parameters=parameters,inputs=inputs,
            decision=DecisionContract('CYCLE_TARGET',0.,1.,'NEXT_SESSION'),
            execution=ExecutionPolicy('FROZEN_RULE',{'capital':{'fee_rate':.001,'mode':'signal_cash_fraction','target_scope':'entry_cycle'},'entry':{'limit_parameter':.01,'order_type':'LIMIT'},'exit':{'limit_ratio':.1,'order_type':'MARKET'},'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001}}),
            monitoring=MonitoringPolicy('OBSERVE',{}),capabilities=RequiredCapabilities(tuple(r.dataset for r in inputs.requirements),('LIMIT','MARKET')),
            tradable_symbol='159326.SZ',observation=ObservationDefinition((ObservationSeries('path_prediction','过去训练模型预测三日净收益','path_prediction'),ObservationSeries('risk_prediction','过去训练模型预测三日风险','risk_prediction'),ObservationSeries('intent_age','固定市场意图周期年龄','intent_age')),()),
            history=HistoryPolicy('CANONICAL_REPLAY','2024-12-31','2024-09-09'))
    @classmethod
    def from_parameters(cls,parameters):return cls(parameters)
    @property
    def definition(self):return self._definition
    def calendar_request(self,tradable_window):
        if tradable_window.start < FIRST or tradable_window.end > LAST:
            raise ValueError('prototype restricted to approved development windows')
        return DataRequest(Dataset.TRADING_CALENDAR,'SZSE','2024-09-09',tradable_window.end.isoformat(),tradable_window.end.isoformat())
    def derive_calculation_scope(self,tradable_window,calendar_dates):
        if tradable_window.start < FIRST or tradable_window.end > LAST:raise ValueError('outside research dates')
        days=tuple(d for d in calendar_dates if tradable_window.contains(d))
        signals={d:max(x for x in calendar_dates if x<d) for d in days};end=max(signals.values());first=min(signals.values())
        if end < FIRST:raise ValueError('prototype requires at least one development signal session')
        calc=tuple(d for d in calendar_dates if date(2024,12,31)<=d<=end);requests={}
        for r in self.definition.inputs.requirements:
            if r.name=='calendar':continue
            intraday=r.name=='intraday';start='2025-01-02' if intraday else '2024-09-09';through=max(FIRST,first) if intraday else first
            requests[r.name]=DataRequest(r.dataset,r.subject,start,end.isoformat(),end.isoformat(),r.frequency,
                coverage=DataCoverageRequirement(maximum_start_lag_days=0,minimum_sessions=r.lookback_sessions,minimum_observations=8 if intraday else 1,observations_through=through.isoformat()))
        return CalculationScope(tradable_window,days,signals,calc,requests)
    def calculate_context_history(self,inputs,context):
        f=causal_features(inputs['market'],inputs['execution'],inputs['intraday'])
        out=intentions(f,self.definition.parameters.values).reindex(context.sessions)
        if out.drop(columns=['entry_allocation_fraction']).isna().any().any():raise ValueError('missing canonical calculation sessions')
        return out
