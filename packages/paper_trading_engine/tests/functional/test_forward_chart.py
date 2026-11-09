from __future__ import annotations


import pytest

from paper_trading_engine.forward_chart import render_forward_chart_html


def _context() -> dict[str, object]:
    return {
        "contract_version": "pte_forward_chart.v2",
        "strategy": {
            "account_id": "s007-v1",
            "strategy_id": "S007",
            "version": "v1",
            "release_id": "S007-v1",
            "release_hash": "a" * 64,
            "name": "多源机会风险门控",
            "symbol": "588080.SH",
        },
        "window": {"selection_data_cutoff": "2026-09-02", "context_sessions": 60},
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
