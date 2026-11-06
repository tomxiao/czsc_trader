"""S001 v4 observation: describe original score and target transitions only."""

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


def observation_definition(legacy, rule):
    score = SignalBasisDefinition('score', text('综合得分 ', SeriesValueRef('score'),
        '；入场门槛 ', GuideValueRef('score','entry'), '，退出门槛 ', GuideValueRef('score','exit'), '。'))
    regime = SignalBasisDefinition('regime', text('当次权重场景：', StateValueRef('regime'), '。'))
    detail = text('策略将30分钟、日线和周线的结构、趋势及量价位置合成为得分，按此前可得的价格路径选择权重。得分不是收益率或上涨概率。',
        '空仓时连续 ', SeriesValueRef('confirm'), ' 达到入场门槛后转为满仓意图；满仓意图至少持续 ',
        SeriesValueRef('minimum'), ' 后，连续 ', SeriesValueRef('exit_confirm'), ' 达到退出门槛才转为空仓。',
        '这里展示原策略已算出的目标变化，不等同于账户已经成交。计时与确认均属于模型意图。')
    cases = (
        SignalExplanationCase('enter',text('出现入场信号'),(score,regime),
            text('关注得分转弱及最短持有意图期限；实际是否买入查看事件区。'),detail),
        SignalExplanationCase('exit',text('出现退出信号'),(score,regime),
            text('等待新的连续入场确认；实际是否卖出查看事件区。'),detail),
        SignalExplanationCase('hold',text('模型继续维持满仓意图'),(score,regime),
            text('退出需要同时满足最短意图期限和连续得分确认，单日低分不等于应立即卖出。'),detail),
        SignalExplanationCase('cash',text('模型保持空仓意图'),(score,regime),
            text('关注得分是否连续 ', SeriesValueRef('confirm'), ' 达到入场门槛。'),detail),
        SignalExplanationCase('initial_long',text('当前模型为满仓意图'),(score,regime),
            text('当前观察首行缺少前一行目标，不据此宣称当日入场；实际持仓查看账户。'),detail),
        SignalExplanationCase('initial_cash',text('当前模型为空仓意图'),(score,regime),
            text('当前观察首行缺少前一行目标，不据此宣称当日退出。'),detail),
    )
    return ObservationDefinition(legacy.series,legacy.facts,signal_panel=SignalPanelDefinition(
        groups=(SignalGroup('score','综合得分','分','冻结权重合成值',ObservationFormat.NUMBER,3),
                SignalGroup('sessions','模型规则期限','个交易日','模型状态机参数',ObservationFormat.INTEGER,0)),
        series=(SignalSeriesDefinition('score','综合得分','score','obs_score',status_field='obs_status',reason_field='obs_reason',
                    guides=(EvidenceGuide('entry','入场门槛','obs_entry'),EvidenceGuide('exit','退出门槛','obs_exit'))),
                SignalSeriesDefinition('confirm','入场确认期','sessions','obs_confirm'),
                SignalSeriesDefinition('minimum','最短持有意图期','sessions','obs_minimum'),
                SignalSeriesDefinition('exit_confirm','退出确认期','sessions','obs_exit_confirm')),
        states=(SignalStateDefinition('action','原模型目标变化','obs_action',
                    tuple(SignalStateOption(c.key,c.judgment.parts[0]) for c in cases),status_field='obs_status',reason_field='obs_reason'),
                SignalStateDefinition('regime','权重场景','obs_regime',
                    (SignalStateOption('trend','趋势场景'),SignalStateOption('range','震荡场景'),
                     SignalStateOption('warmup','场景预热：沿用冻结的预热权重')))),
        explanation=SignalExplanationDefinition('action',cases)))


def observation_history(history, rule):
    result=pd.DataFrame(index=history.index)
    target=history.target_position
    if not target.isin([0.,1.]).all():
        raise ValueError('S001 observation requires original binary target')
    previous=target.shift(1)
    result['obs_action']='cash'
    result.loc[target.eq(1),'obs_action']='hold'
    result.loc[target.eq(1)&previous.eq(0),'obs_action']='enter'
    result.loc[target.eq(0)&previous.eq(1),'obs_action']='exit'
    result.loc[previous.isna()&target.eq(1),'obs_action']='initial_long'
    result.loc[previous.isna()&target.eq(0),'obs_action']='initial_cash'
    result['obs_score']=history.factor_score
    result['obs_regime']=history.regime
    result['obs_entry']=float(rule['entry_threshold'])
    result['obs_exit']=float(rule['exit_threshold'])
    result['obs_confirm']=int(rule['confirm_days'])
    result['obs_minimum']=int(rule['min_hold_days'])
    result['obs_exit_confirm']=int(rule['exit_confirm_days'])
    ready=history.factor_score.notna()
    result['obs_status']=ready.map({True:'AVAILABLE',False:'UNAVAILABLE'})
    result['obs_reason']=ready.map({True:'',False:'当日综合得分缺失'})
    return result
