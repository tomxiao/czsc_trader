"""S001 V5, with persistent CZSC analyzers and an explicit target position."""
import base64
from collections import Counter
from datetime import date, timedelta
import json
import zlib
from zoneinfo import ZoneInfo

import czsc
import pandas as pd

from strategy_runtime import AccountDecision, AccountStepResult, SignalBasisSnapshot, SignalExplanationSnapshot, StateRecord, StepDataWindow
from .signal_math import (_DAILY_CONFIG, _FALLBACK_WEIGHTS, _INTRADAY_CONFIG,
    _WEEKLY_CONFIG, _config_label, _ohlcv, _regimes, _score, _signal_score)

ZONE = ZoneInfo('Asia/Shanghai')
FIRST = date(2020, 11, 16)
SYMBOL = '588080.SH'
CONFIGS = (
    ('daily', '日线', 'daily', 30, _DAILY_CONFIG),
    ('intraday', '30分钟', '30m', 500, _INTRADAY_CONFIG),
    ('weekly', '周线', 'weekly', 10, _WEEKLY_CONFIG),
)
SIGNAL_KEYS = {
    'daily': ('日线_D1_表里关系V230101', '日线_D1五笔_形态V230619', '日线_D1七笔_形态V230620',
              '日线_D1SMA#5_分类V221101', '日线_D1SMA#10_分类V221101', '日线_D1SMA#20_分类V221101',
              '日线_D1MACD12#26#9#MACD_BS辅助V221028', '日线_D1W5M30N10_窗口能量V230731',
              '日线_D1W20_支撑压力V240406'),
    '30m': ('30分钟_D1_表里关系V230101', '30分钟_D1_三买辅助V230228'),
    'weekly': ('周线_D1_表里关系V230101',),
}


def signal_keys(engine, freq, configurations):
    keys = SIGNAL_KEYS[freq]
    if {key for key in engine.s if len(key.split('_')) == 3} != set(keys):
        raise ValueError('S001 冻结因子字段数量变化')
    return dict(zip((_config_label(freq, conf) for conf in configurations), keys, strict=True))


def signal_values(engine, freq, configurations):
    keys = signal_keys(engine, freq, configurations)
    return {label: _signal_score(engine.s.get(key), Counter()) for label, key in keys.items()}


def update_analyzer(snapshot, count, frame, frequency, init_count, configs):
    frame = _ohlcv(frame, SYMBOL)
    bars = czsc.format_standard_kline(frame, freq=frequency)
    bars = [czsc.RawBar(b.symbol, b.dt, b.freq, b.open, b.close, b.high, b.low,
                      b.vol, b.amount, count + i) for i,b in enumerate(bars)]
    if count < init_count:
        old_bars = json.loads(snapshot) if snapshot else []
        rows = old_bars + [[str(b.dt), b.open, b.close, b.high, b.low, b.vol, b.amount] for b in bars]
        if len(rows) < init_count:
            return json.dumps(rows, separators=(',', ':')), count + len(bars), None
        initial = [czsc.RawBar(SYMBOL, pd.Timestamp(t), bars[0].freq, o, c, h, l, v, a, i)
                   for i, (t, o, c, h, l, v, a) in enumerate(rows[:init_count])]
        bg = czsc.BarGenerator(base_freq=frequency, freqs=[])
        bg.init_freq_bars(frequency, initial)
        engine = czsc.CzscTrader(bg, [], [dict(c) for c in configs])
        bars = bars[init_count-count:]
    else:
        engine = restore(snapshot)
    for bar in bars:
        engine.update_signals(bar)
    return pack(engine), count + (len(frame)), engine if bars else None


def pack(engine):
    return base64.b64encode(zlib.compress(engine.dump_state(), level=1)).decode('ascii')


def restore(snapshot):
    return czsc.CzscTrader.restore_state(zlib.decompress(base64.b64decode(snapshot, validate=True)))


def signal_step(prior, score, rule):
    active, enter, exits, held = (prior[key] for key in ('target', 'enter_count', 'exit_count', 'holding_days'))
    if not active:
        enter = enter + 1 if score >= rule['entry_threshold'] else 0
        if enter >= rule['confirm_days']:
            active, enter, exits, held = 1, 0, 0, 1
    else:
        eligible = held >= rule['min_hold_days']
        exits = exits + 1 if eligible and score <= rule['exit_threshold'] else 0
        if exits >= rule['exit_confirm_days']:
            active, enter, exits, held = 0, 0, 0, 0
        else:
            held += 1
    return dict(target=active, enter_count=enter, exit_count=exits, holding_days=held)


def explain(target, previous, score, regime, rule):
    entry, exit_ = float(rule['entry_threshold']), float(rule['exit_threshold'])
    regime = {'trend': '趋势', 'range': '震荡', 'warmup': '预热'}[regime]
    if target and not previous:
        judgment, summary = '触发入场', f'{regime}档综合评分达到入场线，确认条件已满足。'
    elif previous and not target:
        judgment, summary = '目标清仓', f'{regime}档评分触及退出线，持有期和退出确认已满足。'
    elif target:
        judgment = '延续目标仓位'
        summary = ('综合评分仍高于退出线，延续目标仓位。' if score > exit_
                   else '评分已触及退出线，最短持有或连续确认条件尚未满足。')
    else:
        judgment = '继续空仓'
        summary = ('综合评分低于入场线，继续空仓。' if score < entry
                   else '综合评分已达到入场线，连续确认条件尚未满足。')
    details = (f'{regime}档评分 {score:.6g}，入场线 {entry:.6g}，退出线 {exit_:.6g}。'
               f'入场须连续 {rule["confirm_days"]} 日达标；退出须满足最短持有 '
               f'{rule["min_hold_days"]} 日，并连续 {rule["exit_confirm_days"]} 日确认。周线因子使用已完成周线。')
    basis = (SignalBasisSnapshot('summary', summary), SignalBasisSnapshot('conditions', details))
    return AccountDecision(float(target), SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis,
        '下一交易日收盘后复核综合评分及确认条件。', f'{summary} {details}'))


def step(ctx, state):
    prior = dict(state.account.values)
    day = ctx.point.observed_through.astimezone(ZONE).date()
    execution_day = ctx.point.execution_interval.start.astimezone(ZONE).date()
    if execution_day <= day:
        raise ValueError('S001 需要下一交易日的执行时点')
    previous = prior['last_signal_date']
    if previous is None:
        if day != FIRST:
            raise ValueError('S001 首次运行须从规范起点初始化，或导入已验证的续算快照')
    else:
        first = date.fromisoformat(previous) + timedelta(days=1)
        cal = ctx.dfls.fetch(StepDataWindow('calendar', first, day))
        if (not pd.DatetimeIndex(cal.Date).equals(pd.date_range(first,day))
                or cal.loc[cal.IsOpen.eq(1), 'Date'].dt.date.tolist() != [day]):
            raise ValueError('S001 前一交易日状态缺失')
    monday = day - timedelta(days=day.weekday())
    next_monday = execution_day - timedelta(days=execution_day.weekday())
    frames = {
        'daily': ctx.dfls.fetch(StepDataWindow('adjusted_daily', day, day)),
        'intraday': ctx.dfls.fetch(StepDataWindow('adjusted_30m', day, day)),
    }
    if next_monday != monday:
        frames['weekly'] = ctx.dfls.fetch(StepDataWindow('adjusted_weekly', monday, day))
    if (list(frames['daily'].Date.dt.date) != [day] or len(frames['intraday']) != 8
            or ('weekly' in frames and list(frames['weekly'].Date.dt.date) != [day])):
        raise ValueError('S001 信号日行情切片不完整')
    following = dict(prior)
    factors = {}
    for name, frequency, key, init_count, configs in CONFIGS:
        frame = frames.get(name)
        if frame is None:
            factors.update(json.loads(prior['weekly_factors']))
            continue
        snapshot, count, engine = update_analyzer(prior[name],prior[name+'_count'],frame,frequency,init_count,configs)
        following[name], following[name+'_count'] = snapshot, count
        values = {} if engine is None else signal_values(engine,key,configs)
        factors.update(values)
        if name == 'weekly':
            following['weekly_factors'] = json.dumps(values, separators=(',', ':'))
    rule = json.loads(ctx.parameters['rule'])
    past = json.loads(prior['recent_closes'])
    closes = past + [float(frames['daily'].Close.iloc[0])]
    regime = _regimes(pd.Series(closes), rule['er_lookback'], rule['er_threshold']).iloc[-1]
    weights = _FALLBACK_WEIGHTS if regime == 'warmup' else rule['weights'][regime]
    values = pd.DataFrame([{factor: factors.get(factor,0.0) for factor in rule['factor_names']}])
    score = float(_score(values, weights).iloc[0])
    following.update(signal_step(prior,score,rule))
    following['recent_closes'] = json.dumps(closes[-rule['er_lookback']-1:], separators=(',', ':'))
    following['last_signal_date'] = day.isoformat()
    return AccountStepResult(explain(following['target'],prior['target'],score,regime,rule),
                             StateRecord(tuple(following.items())),StateRecord())
