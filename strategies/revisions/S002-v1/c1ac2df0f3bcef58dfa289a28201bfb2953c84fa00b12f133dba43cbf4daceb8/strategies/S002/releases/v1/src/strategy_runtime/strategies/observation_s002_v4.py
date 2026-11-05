"""S002 v4 observation: project the existing state-machine action, never trade."""

import pandas as pd

from strategy_runtime import (
    ObservationDefinition, ObservationFormat, EvidenceGuide,
    SignalGroup, SignalSeriesDefinition, SignalPanelDefinition,
    SignalStateDefinition, SignalStateOption, SignalExplanationDefinition,
    SignalExplanationCase, SignalText, SignalBasisDefinition,
    SeriesValueRef, GuideValueRef, StateValueRef,
)


def text(*parts):
    return SignalText(parts)


def observation_definition(legacy, signal, portfolio):
    shape = str(signal['entry_state'])
    duration = text('模型意图自激活日起计时，持续 ', GuideValueRef('age', 'limit'),
                    ' 后结束；账户成交日和实际持仓可能不同。')
    cases = (
        SignalExplanationCase('enter', text('出现入场信号'),
            (SignalBasisDefinition('event', text('形态首次切换到 ', StateValueRef('shape'), '，原状态机激活一轮持有意图。')),),
            text('关注模型意图是否达到 ', GuideValueRef('age', 'limit'), ' 的期限。'), duration),
        SignalExplanationCase('hold_position', text('本轮持有信号仍有效'),
            (SignalBasisDefinition('age', text('距意图激活已过 ', SeriesValueRef('age'), '；期限 ', GuideValueRef('age', 'limit'), '。')),),
            text('达到期限后模型转为空仓；成交情况查看事件区。'), duration),
        SignalExplanationCase('ignore_entry_while_holding', text('继续原持有意图，不重复入场'),
            (SignalBasisDefinition('event', text('再次出现新形态事件，但原状态机仍处于持有阶段。')),
             SignalBasisDefinition('age', text('距原意图激活已过 ', SeriesValueRef('age'), '；期限 ', GuideValueRef('age', 'limit'), '。'))),
            text('按原期限退出；新事件不重置计时。'), duration),
        SignalExplanationCase('exit_time', text('出现退出信号：模型期限已到'),
            (SignalBasisDefinition('age', text('距意图激活已过 ', SeriesValueRef('age'), '，达到期限 ', GuideValueRef('age', 'limit'), '。')),),
            text('等待形态离开后再次切入 ', shape, '；持续同一形态不会立即重入。'),
            text('到期退出优先于当日新事件。', *duration.parts)),
        SignalExplanationCase('hold_cash', text('保持空仓意图，等待新事件'),
            (SignalBasisDefinition('shape', text('当日形态：', StateValueRef('shape'), '。原状态机未激活新一轮意图。')),),
            text('等待形态由其他状态切换到 ', shape, '；不是看到该形态就每天重复买入。'),
            text('策略尝试捕捉连续走弱后的短期修复；只在形态新出现时激活。', *duration.parts)),
    )
    return ObservationDefinition(legacy.series, legacy.facts, signal_panel=SignalPanelDefinition(
        groups=(SignalGroup('sessions', '模型计时', '个交易日', '信号激活后的交易日差', ObservationFormat.INTEGER, 0),),
        series=(SignalSeriesDefinition('age', '距意图激活已过', 'sessions', 'obs_age',
            guides=(EvidenceGuide('limit', '意图期限', 'obs_limit'),)),),
        states=(
            SignalStateDefinition('action', '实际模型分支', 'obs_action',
                tuple(SignalStateOption(c.key, c.judgment.parts[0]) for c in cases),
                status_field='obs_status', reason_field='obs_reason'),
            SignalStateDefinition('shape', '当日形态', 'obs_shape',
                (SignalStateOption('active', shape), SignalStateOption('inactive', '非'+shape)),
                status_field='obs_status', reason_field='obs_reason'),
        ), explanation=SignalExplanationDefinition('action', cases)))


def observation_history(history, signal, portfolio):
    result = pd.DataFrame(index=history.index)
    actions = {'ENTER':'enter', 'HOLD_POSITION':'hold_position',
               'IGNORE_ENTRY_WHILE_HOLDING':'ignore_entry_while_holding',
               'EXIT_TIME':'exit_time', 'HOLD_CASH':'hold_cash'}
    if not history.action.isin(actions).all():
        raise ValueError('S002 observation encountered an undeclared trading action')
    result['obs_action'] = history.action.map(actions)
    result['obs_age'] = history.held_sessions
    result['obs_limit'] = int(portfolio['holding_sessions'])
    result['obs_shape'] = history.factor_score.map({1.0:'active', 0.0:'inactive'})
    ready = history.signal_state.notna() & history.factor_score.notna()
    result['obs_status'] = ready.map({True:'AVAILABLE',False:'UNAVAILABLE'})
    result['obs_reason'] = ready.map({True:'',False:'当日形态计算结果缺失'})
    return result
