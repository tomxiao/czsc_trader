"""Prospective EX092 centered negative gap/body dependence, zero accounts.

Definition freezes sources and method without reading real price contents.
Only root-authorized explicit declare/study/audit invocations perform phases.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp/s013-new-goal'))
import governance as g  # noqa: E402

WORK = Path(__file__).resolve().parent
OUT = ROOT / '.tmp/s013-new-goal/result092'
NUMERIC = ROOT / 'research/S013/experiments/EX075_20261011/src/statistics_draft_v2.py'
ORDER = ROOT / 'research/S013/experiments/EX068_20261011/src/order_component.py'
OLD75 = ROOT / 'research/S013/experiments/EX075_20261011/src/component_draft.py'
DIRECTIONS = ROOT / '.tmp/s013-new-goal/prospective_directions.json'


def definition():
    for name in ('checks.json', 'audit_checks.json', 'audit_statistics_checks.json', 'kernel_checks.json'):
        check = g.read(WORK / name)
        real_inputs_key = 'real_inputs_read' if name in ('audit_checks.json', 'audit_statistics_checks.json') else 'real_inputs'
        if check['status'] != 'PASS' or check[real_inputs_key] != 0:
            raise ValueError('All pure synthetic checks must pass before declaration')
        for source, expected in check.get('files', {}).items():
            if g.digest(WORK / source) != expected:
                raise ValueError('Checked source drift: ' + source)
        if name == 'audit_statistics_checks.json':
            for source, expected in check['source_sha256'].items():
                if g.digest(WORK / source) != expected:
                    raise ValueError('Independent statistics checked source drift: ' + source)
    if g.read(WORK / 'kernel_checks.json')['source_sha256'] != g.digest(WORK / 'kernel.py'):
        raise ValueError('Checked primary statistics drift')
    if g.read(WORK / 'kernel_checks.json')['checks_source_sha256'] != g.digest(WORK / 'kernel_checks.py'):
        raise ValueError('Primary synthetic checker drift')
    direction = g.read(DIRECTIONS)
    if len(direction['directions']) != 1 or direction['directions'][0]['id'] != 'JOINT_OVERNIGHT_AND_INTRADAY_DOWNSIDE_DEPENDENCE20':
        raise ValueError('Only the pre-reviewed fixed co-down direction is permitted')
    previous = g.read(ROOT / 'research/S013/experiments/EX091_20261012/protocols/plan.json')
    kernel = g.base.load('co_down_prospective_definition', WORK / 'kernel.py')
    if len(kernel.CONTROLS) != 27 or len(set(kernel.CONTROLS)) != 27:
        raise ValueError('Exactly27 unique controls required before declaration')
    names = ('features.py', 'checks.py', 'checks.json', 'kernel.py', 'kernel_checks.py', 'kernel_checks.json',
             'audit_features.py', 'audit_checks.py', 'audit_checks.json',
             'audit_statistics.py', 'audit_statistics_checks.py', 'audit_statistics_checks.json', 'driver.py')
    sources = [(WORK / name).relative_to(ROOT).as_posix() for name in names]
    sources += [NUMERIC.relative_to(ROOT).as_posix(), ORDER.relative_to(ROOT).as_posix(), OLD75.relative_to(ROOT).as_posix(),
                DIRECTIONS.relative_to(ROOT).as_posix(), '.tmp/s013-new-goal/governance.py',
                '.tmp/s013-new-goal/gates_v2.py', '.tmp/s013_confirm_execution.py',
                'research/S013/experiments/EX058_20261011/src/common.py',
                'research/S013/experiments/EX083_20261012/src/kernel.py',
                'research/S013/experiments/EX083_20261012/src/audit.py']
    return {
        'question': '过去20日隔夜与当日日内负变动同时发生的中心化依赖，能否在各负幅/频率边际及原信息之外识别较差h4做多机会？',
        'basis': '预先只读重复性评审保留唯一弱先验交互：EX060分开负能量、EX064缺口修复/回吐、EX069四日支配份额不包含负变动逐日配对；不是新市场信息或已有盈利发现。',
        'strongest_counter': '各负幅和频率已可能解释关联，EX060/64/69与风险过滤/提前退出有失败反证；20日状态及未来4日高度重叠，同池多轮选择，风险过滤可能排除盈利年反弹。',
        'role_of_component': '入场风险职责：旧每日隔夜/日内负幅配对的新非线性表达，尚无预测支持',
        'label': '原h4双边10bp后复权OPEN净标签；Open[T+5]/Open[T+1]*.999/1.001-1；maturity=T+5OPEN',
        'horizon': 'h4唯一主要标签；固定过去20完整日含T及一个前Close，不扫窗口或选择h8救援',
        'controls': '固定原14+mean_a20/mean_b20/rms_a20/rms_b20/freq_a20/freq_b20+EX0612+EX0684+EX075samebar_cov，共27；配对控制及增广均要求全部28列有限',
        'control_columns': list(kernel.CONTROLS), 'ordered_feature_columns': [*kernel.CONTROLS, 'X'],
        'component_source_column': 'co_down_dependence20',
        'availability': 'T收盘已知；20日含T且真实前Close，无足历史NA；任一负能量为0仅X不可得；年度训练仅2020起此前年度已成熟标签、label_end<本年首T；不futuretestcountgate，不年度重置特征',
        'price_basis': '原S013510500开发池HFQ固定锚、不另叠加分红；100万元整手100、单侧10bp、固定1%执行合同',
        'limitations': '组件代理不是原生账户/年度净收益/实际闭合次数/标准32；现有1637prices仅anchor+eval，初20支持不足留NA，不新增2019输入或训练；旧信息压缩不是独立数据',
        'hypothesis': 'a=max(-log(O/Cprev),0),b=max(-log(C/O),0);X=(mean20ab-mean20a*mean20b)/sqrt(mean20a2*mean20b2)，固定negative→较低h4扣费净收益，不能翻号/改窗',
        'method': '与EX091相同纯统计数学：全1635轴raw/27controls partial rankIC，原轴500overlap40 seed13 LINEAR95，20n/10residDF/400valid；年度2021..26同28支持trainECDFmidpoint+ridge10controls/+X，train40；4预测数量及18全部时钟',
        'stop_or_followup': '主要净增量及经济余量不足则停止固定表达，不翻符号/去边际/改窗/选择年度相位/持有期救援；有明确经济依据才另冻结原生中心计划',
        'new_goal': 'MANDATE/7；中心及标准32全部过新版四门，盈利年份合并频率替代全期；全年BH盈亏仅事后验收',
        'direction_review_source': DIRECTIONS.relative_to(ROOT).as_posix(),
        'resources': {'one_statistical_study': 1, 'maximum_new_models': 12, 'new_accounts': 0, 'provider_calls': 0},
        'input_references': previous['input_references'],
        'native_cache_sha256': previous['native_cache_sha256'],
        'source_files': {name: g.digest(ROOT / name) for name in sources},
    }


def frame(ref):
    value = pd.read_csv(g.public(ref), index_col='signal_date', float_precision='round_trip')
    value.index = pd.to_datetime(value.index).as_unit('ns')
    return value


def inputs(plan):
    refs = plan['input_references']
    old14, old75, old68, labels, prices = (frame(refs[name]) for name in ('features14.csv', 'features75.csv', 'features68.csv', 'labels.csv', 'prices.csv'))
    c = g.base.common()
    cache = ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz'
    if g.digest(cache) != plan['native_cache_sha256']:
        raise ValueError('Native cached input changed')
    bound, account = c.cache_read(cache)
    if serialize_evaluation_evidence(bound, account) != g.read(g.public(refs['native_account.json'])):
        raise ValueError('Native cache must equal the authenticated public account')
    ed = bound.execution_data
    native_prices = ed.execution_daily.set_index('dt')[['open', 'close']].copy()
    native_prices.index = pd.to_datetime(native_prices.index).as_unit('ns')
    pd.testing.assert_frame_equal(prices[['open', 'close']], native_prices, check_exact=True, check_names=False)
    calendar = pd.DatetimeIndex(pd.to_datetime(ed.evaluation_sessions)).as_unit('ns').normalize()
    full_calendar = prices.index
    axis = old14.index
    if len(axis) != 1635 or not axis.equals(calendar[:-1]) or len(full_calendar) != 1637 or not full_calendar[1:].equals(calendar):
        raise ValueError('Original anchor+evaluation calendar and signal axis required')
    if full_calendar[0] != pd.Timestamp('2019-12-31') or full_calendar[-1] != pd.Timestamp('2026-09-30'):
        raise ValueError('No new warmup or extended prices permitted')
    bars = ed.execution_intraday.rename(columns={'dt': 'Date', 'open': 'Open', 'close': 'Close', 'vol': 'Volume'})[['Date', 'Open', 'Close', 'Volume']].copy()
    bars['Date'] = pd.to_datetime(bars.Date).dt.as_unit('ns')
    if not pd.DatetimeIndex(bars.Date).normalize().unique().equals(calendar):
        raise ValueError('Exact old native complete intraday calendar required')
    k = g.base.load('co_down_definition', WORK / 'kernel.py')
    f = g.base.load('co_down_features', WORK / 'features.py')
    new, trace = f.build(prices[['open', 'close']], axis, full_calendar)
    old_order = g.base.load('co_down_frozen_order', ORDER).build_features(bars.set_index('Date')).loc[axis]
    old_covariance, _ = g.base.load('co_down_frozen_samebar', OLD75).features(bars.set_index('Date'))
    for name in old_order:
        np.testing.assert_allclose(old_order[name], old68[name], rtol=2e-12, atol=2e-14, equal_nan=True)
    for name in k.ORIGINAL:
        pd.testing.assert_series_equal(old14[name], old75[name], check_exact=True, check_names=False)
        pd.testing.assert_series_equal(old14[name], old68[name], check_exact=True, check_names=False)
    np.testing.assert_allclose(old_covariance.loc[axis, 'down_volume_cov'], old75.down_volume_cov, rtol=2e-11, atol=2e-14, equal_nan=True)
    marginal_names = list(f.COLUMNS[1:])
    cov = old_covariance.loc[axis, ['down_volume_cov']].rename(columns={'down_volume_cov': 'samebar_cov'})
    features = old14[list(k.ORIGINAL)].join(new[marginal_names]).join(old75[['late_recovery', 'early_volume_reclaim']]).join(old_order).join(cov)
    features['X'] = new.co_down_dependence20
    features = features[[*k.CONTROLS, 'X']]
    labels['label_end_return_4'] = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    raw = prices.open.shift(-5) / prices.open.shift(-1) * (.999 / 1.001) - 1
    ends = pd.Series(prices.index, index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4, raw.reindex(axis), rtol=2e-11, atol=2e-13, equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4, ends.reindex(axis))
    if not features.index.equals(labels.index) or features.columns.tolist() != plan['ordered_feature_columns']:
        raise ValueError('Frozen feature/label identity and order required')
    assert not c.SOURCE_CALLS
    return features, labels, prices[['open', 'close']], new, trace


def declare():
    plan = definition()
    exp, plan, refs = g.allocate(92, title='隔夜及当日日内共同下跌的边际控制增量', question=plan['question'], plan=plan, checks=g.read(WORK / 'kernel_checks.json'))
    OUT.mkdir(parents=True, exist_ok=True)
    g.write(OUT / 'declaration.json', {'experiment': exp.to_dict(), 'new_accounts': 0, 'quota_slot': 4})
    print({'experiment': exp.experiment_id, 'stage': 'DECLARED', 'new_accounts': 0}, flush=True)


def study():
    exp, path, plan, method_refs = g.stage(92)
    g.write(OUT / 'study_attempt.json', {'status': 'STARTED', 'study_limit': 1, 'new_accounts': 0})
    features, labels, prices, new, trace = inputs(plan)
    k = g.base.load('co_down_primary', WORK / 'kernel.py')
    numeric = g.base.load('co_down_frozen_numeric', NUMERIC)
    clock = g.base.load('co_down_existing_clock', ROOT / 'research/S013/experiments/EX083_20261012/src/kernel.py')
    scores, traces = k.forecasts(features, labels, numeric)
    stats = k.analyze(features, labels, scores, traces, numeric, clock)
    if stats['new_models'] > 12 or stats['fixed_hypothesis'] != 'negative' or stats['new_accounts'] != 0:
        raise ValueError('Fixed model/account/hypothesis bounds violated')
    for name, table in (('features.csv', features), ('co_down_features.csv', new), ('forecasts.csv', scores)):
        with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
            table.to_csv(stream, index_label='signal_date', float_format='%.17g')
    g.write(OUT / 'availability.json', trace)
    g.write(OUT / 'statistics.json', stats)
    g.write(OUT / 'input_checks.json', {'status': 'PASS', 'signals': len(features), 'same_native_source': 'PUBLIC_EXACT',
        'native_daily_prices': 'PUBLIC_EXACT', 'calendar': 'ORIGINAL1637_ANCHOR_AND_EVALUATION',
        'warmup_extension': False, 'first20_support': 'INSUFFICIENT_HISTORY_NA_RETAINED',
        'feature_reason_counts': {reason: sum(row['reason'] == reason for row in trace) for reason in sorted({row['reason'] for row in trace})},
        'old14_EX061_EX068_EX075': 'EXACT_OR_ROUNDOFF_TOLERANCE', 'HFQ_OPEN_labels': 'EXACT',
        'actual_complete_analyses': 1, 'actual_models': stats['new_models'], 'new_accounts': 0, 'provider_calls': 0})
    c = g.base.common()
    refs = {name: g.put(c.context(1), exp, OUT / name) for name in ('features.csv', 'co_down_features.csv', 'forecasts.csv', 'availability.json', 'statistics.json', 'input_checks.json')}
    g.write(path / 'protocols/result_references.json', refs)
    assert not c.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'stage': 'COMPLETE', 'new_models': stats['new_models'], 'new_accounts': 0}, flush=True)


def audit():
    exp, path, plan, method_refs = g.stage(92)
    features, labels, prices, new, trace = inputs(plan)
    out_refs = g.read(path / 'protocols/result_references.json')
    reported_features = frame(out_refs['features.csv'])
    pd.testing.assert_frame_equal(features, reported_features, check_exact=True)
    reported_new = frame(out_refs['co_down_features.csv'])
    pd.testing.assert_frame_equal(new, reported_new, check_exact=True)
    if g.read(g.public(out_refs['availability.json'])) != trace:
        raise ValueError('Reported feature availability differs')
    feature_proof = g.base.load('co_down_features_oracle', WORK / 'audit_features.py').verify(prices, features.index, prices.index, reported_new, trace)
    statistics_proof = g.base.load('co_down_statistics_oracle', WORK / 'audit_statistics.py').verify(features, labels, frame(out_refs['forecasts.csv']), g.read(g.public(out_refs['statistics.json'])),
        g.base.load('co_down_clock_oracle', ROOT / 'research/S013/experiments/EX083_20261012/src/audit.py'))
    g.write(OUT / 'verification.json', {'status': 'PASS', 'feature_audit': feature_proof, 'statistics_audit': statistics_proof,
        'new_accounts': 0, 'provider_calls': 0, 'plan_reference': method_refs['plan.json'], 'result_references': out_refs})
    c = g.base.common()
    g.write(path / 'protocols/audit_reference.json', g.put(c.context(1), exp, OUT / 'verification.json'))
    assert not c.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'audit': 'PASS', 'new_accounts': 0}, flush=True)


if __name__ == '__main__':
    {'declare': declare, 'study': study, 'audit': audit}[sys.argv[1]]()
