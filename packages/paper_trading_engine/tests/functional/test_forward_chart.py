from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trading_engine.forward_chart import FORWARD_CHART_CONTRACT_VERSION, render_forward_chart_html


def test_mu_no_order_decision_drives_chart_start_and_saved_explanation(tmp_path):
    from paper_trading_engine.account_chart import AccountChartService
    from paper_trading_engine.equity_inspection import _inspect_forward_chart

    explanation = {"state_key": "decision", "case_key": "wait", "judgment": "no opportunity",
                   "basis": [{"key": "target", "text": "target_weight: 0"}],
                   "next_watch": "next completed daily bar", "explanation": "wait"}
    row = {"account_id": "s018-v1", "decision_id": "mu-first", "signal_date": "2026-11-06",
           "valid_session": "2026-11-09", "generated_at": "2026-11-08T13:36:43+00:00",
           "status": "COMPLETED", "state_reason": "NO_ORDER", "state_changed_at": None,
           "state_events": [], "payload": {"action": "WAIT", "target_quantity": 0, "observation": None,
                                           "strategy_output": {"explanation": explanation}}}
    account = {"account_id": "s018-v1", "symbol": "MU", "asset_type": "stock", "strategy_id": "S018",
               "strategy_version": "v1", "strategy_name_snapshot": "MU", "release_hash": "a" * 64,
               "selection_data_cutoff": "2026-10-30", "channel_id": "futu_US_sim_channel"}
    store = SimpleNamespace(account_decisions=lambda _: [row], account_intents=lambda _: [],
                            account_fills=lambda _: [], account_snapshots=lambda _: [],
                            virtual_account=lambda _: account)
    bars = pd.DataFrame([{"Date": day, "Open": 1, "High": 2, "Low": 1, "Close": 2}
                         for day in ("2026-11-05", "2026-11-06")])
    market_data = SimpleNamespace(history=lambda **_: ("data", bars))
    service = AccountChartService(store, market_data=market_data, cache_dir=tmp_path)
    try:
        result = service._request(account)
        assert result["window"]["forward_observation_start"] == "2026-11-06"
        assert result["window"]["selection_data_cutoff"] == "2026-10-30"
        assert result["strategy"]["currency"] == "USD"
        assert result["observations"] == []
        decision, = result["execution"]["decisions"]
        assert decision["explanation"] == explanation
        assert decision["state_reason"] == "NO_ORDER"
        assert 'no opportunity' in render_forward_chart_html(result)
    finally:
        service.close()
    artifact = _inspect_forward_chart(store, {"decisions": [row]}, market_data, tmp_path)
    assert artifact["status"] == "PASS"
    assert artifact["first_signal_date"] == "2026-11-06"
    assert artifact["decision_count"] == 1
    assert "no opportunity" in artifact["html"]
    assert "/static/strategy-chart.js" not in artifact["html"]
    row["payload"]["strategy_output"].clear()
    with pytest.raises(ValueError, match="missing the saved V4 explanation"):
        _inspect_forward_chart(store, {"decisions": [row]}, market_data, tmp_path)


@pytest.mark.parametrize(
    'signal_date,target,judgment,trigger,order,planning,status,reason',
    [
        ('2026-03-04', 1.0, '延续目标仓位', 'PREVIOUS_ZERO_FILL', {'side': 'BUY', 'quantity': 100300},
         {'status': 'CONSTRAINED', 'reasons': ['INSUFFICIENT_CASH'], 'desired_quantity': 103600,
          'planned_quantity': 100300}, 'INCOMPLETE', 'EXECUTION_EXPIRED'),
        ('2026-03-05', 0.0, '目标清仓', 'TARGET_CHANGED', None,
         {'status': 'NO_CHANGE', 'reasons': [], 'desired_quantity': 0, 'planned_quantity': 0},
         'COMPLETED', 'NO_ORDER'),
    ],
    ids=['s011-renewed-buy-expired', 's011-zero-target-already-flat'],
)
def test_s011_decision_projection_keeps_strategy_and_execution_facts(
    signal_date, target, judgment, trigger, order, planning, status, reason,
):
    from paper_trading_engine.account_chart import AccountChartService

    orders = [order] if order is not None else []
    explanation = {'state_key': 'decision', 'case_key': 'target', 'judgment': judgment,
                   'basis': [{'key': 'target', 'text': judgment}], 'next_watch': '下一个信号日',
                   'explanation': judgment}
    event = AccountChartService._decision_event({
        'account_id': 's011', 'decision_id': signal_date, 'signal_date': signal_date,
        'valid_session': '2026-03-06', 'generated_at': f'{signal_date}T12:00:00Z',
        'status': status, 'state_reason': reason, 'state_changed_at': None, 'state_events': [],
        'payload': {'actual_quantity': 0, 'orders': orders, 'target_quantity': planning['planned_quantity'],
                    'strategy_output': {'explanation': explanation, 'execution_plan': {
                        'target': target, 'execution_trigger': trigger, 'planning_result': planning,
                    }}},
    })
    assert event['explanation']['judgment'] == judgment
    assert (event['target_position'], event['position_at_decision']) == (target, 0)
    assert event['execution_plan'] == {'orders': orders, 'trigger': trigger, 'planning_result': planning}
    assert (event['status'], event['state_reason']) == (status, reason)


def _context() -> dict[str, object]:
    return {
        "contract_version": FORWARD_CHART_CONTRACT_VERSION,
        "strategy": {
            "account_id": "s007-v1",
            "strategy_id": "S007",
            "version": "v1",
            "release_id": "S007-v1",
            "release_hash": "a" * 64,
            "name": "多源机会风险门控",
            "symbol": "588080.SH",
            "currency": "CNY",
        },
        "window": {"selection_data_cutoff": "2026-09-02", "context_sessions": 60,
                   "forward_observation_start": "2026-09-03"},
        "market_data": {
            "identity": "b" * 64,
            "adjustment": "hfq",
            "as_of": "2026-09-03",
            "bars": [
                {"date": "2026-09-02", "open": 1, "high": 1.1, "low": 0.9, "close": 1},
                {"date": "2026-09-03", "open": 1, "high": 1.2, "low": 0.9, "close": 1.1},
            ],
        },
        "observations": [
            {
                "account_id": "s007-v1",
                "symbol": "588080.SH",
                "decision_id": "DEC-1",
                "signal_date": "2026-09-03",
                "valid_session": "2026-09-04",
                "generated_at": "2026-09-03T12:00:00+00:00",
                "action": "BUY",
                "target_quantity": 1000,
                "observation": {
                    "facts":[],
                    "status": "READY",
                    "series": [{
                        "key": "base_score", "label": "基础分", "value": 0.3,
                        "guides": [{"key": "entry", "label": "入场阈值", "value": 0.2}],
                    }],
                },
            }
        ],
        "execution": {
            "decisions": [{
                "account_id": "s007-v1", "decision_id": "DEC-1",
                "signal_date": "2026-09-03", "valid_session": "2026-09-04",
                "generated_at": "2026-09-03T12:00:00+00:00",
                "action": "BUY", "target_quantity": 1000, "status": "ACTIVE",
            }],
            "intents": [], "fills": [], "snapshots": [],
        },
    }


# Independent risk: PTE25; responsibility-level assertions.
@pytest.mark.parametrize('field,value', [
    ('account_id','foreign-account'),
], ids=['PTE25-C01'])
def test_forward_chart_rejects_foreign_observation(field,value):
    context = _context()
    context['observations'][0][field] = value
    with pytest.raises(ValueError, match='differs'):
        render_forward_chart_html(context)


def test_forward_chart_requires_channel_currency():
    context = _context()
    assert '"currency":"CNY"' in render_forward_chart_html(context)
    del context["strategy"]["currency"]
    with pytest.raises(ValueError, match="explicit channel currency"):
        render_forward_chart_html(context)


# Independent risk: PTE25; responsibility-level assertions.
@pytest.mark.parametrize('version', [
    None,
], ids=['PTE25-C02'])
def test_historical_numeric_observations_remain_readable_without_enhanced_fields(version):
    from paper_trading_engine.account_chart import AccountChartService

    context = _context()
    observation = dict(context['observations'][0]['observation'])
    if version is not None:
        observation['contract_version'] = version
    row = {**context['observations'][0], 'payload': {
        'observation': observation, 'symbol': '588080.SH', 'action': 'BUY',
        'target_quantity': 1000,
    }}
    projected = AccountChartService._decision(row)
    assert projected['observation'] == context['observations'][0]['observation']
    assert set(projected['observation']) == {'status', 'series', 'facts'}
    context['observations'] = [projected]
    assert '基础分' in render_forward_chart_html(context)

    # A historical version marker cannot bypass enhanced-snapshot identity
    # validation, and historical numeric values retain their strict contract.
    observation['signal_panel'] = _signal_panel()
    with pytest.raises(ValueError, match='unsupported chart observation contract'):
        AccountChartService._decision(row)
    del observation['signal_panel']
    observation['series'][0]['value'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        AccountChartService._decision(row)


def _signal_panel():
    return {
        "groups": [{"key": "space", "label": "机会空间", "unit": "%", "basis": "相对变化",
                    "format": "PERCENT", "precision": 2, "description": "相对参考中心的距离"}],
        "series": [{"key": "space", "label": "空间", "group": "space", "render": "LINE",
                    "description": "机会有效时的空间", "value": None, "status": "INACTIVE",
                    "reason": "机会已结束", "segment_id": None, "guides": []}],
        "states": [{"key": "opportunity", "label": "机会", "description": "策略机会状态",
                    "options": [{"key": "active", "label": "有效"}, {"key": "inactive", "label": "未激活"}],
                    "value": "inactive", "status": "AVAILABLE", "reason": None}],
    }


# Independent risk: PTE25; responsibility-level assertions.
@pytest.mark.parametrize('version', [
    'strategy_observation.v4',
], ids=['PTE25-C03'])
def test_unavailable_observation_preserves_reason_without_values(version):
    from paper_trading_engine.account_chart import AccountChartService

    context = _context()
    failure = {"contract_version": version, "status": "UNAVAILABLE",
               "message": "观察计算失败：缺少历史字段"}
    row = {**context["observations"][0], "payload": {
        "observation": failure, "symbol": "588080.SH", "action": "WAIT", "target_quantity": 0,
    }}
    assert AccountChartService._has_chart_observation(row)
    assert not AccountChartService._has_ready_observation(row)
    projected = AccountChartService._decision(row)
    assert projected["observation"] == {"status": "UNAVAILABLE", "message": failure["message"]}
    context["observations"] = [projected]
    html = render_forward_chart_html(context)
    assert failure["message"] in html
    assert "signal_panel" not in html
