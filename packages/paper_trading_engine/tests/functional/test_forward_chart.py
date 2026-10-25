from __future__ import annotations

import json
import re

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


def test_pte_forward_chart_is_self_contained_and_titled_by_release() -> None:
    context = _context()
    reason = '完整解释内容' * 100
    context['observations'][0]['observation']['facts'] = [
        dict(key='reason', label='理由', value_type='TEXT', format='TEXT', value=reason),
    ]
    html = render_forward_chart_html(context)

    assert html.startswith("<!doctype html>")
    assert "S007-v1 · 多源机会风险门控" in html
    assert 'href="/static/forward-chart.css"' in html
    assert 'src="/static/forward-chart.js"' in html
    payload = json.loads(re.search(
        r'<script id="forward-context" type="application/json">(.*?)</script>', html
    ).group(1))
    assert payload["strategy"]["release_id"] == "S007-v1"
    assert payload["observations"][0]["observation"]["series"][0]["label"] == "基础分"
    assert reason in html
    assert payload["observations"][0]["observation"]["facts"][0]["value"] == reason
    assert payload["execution"]["decisions"][0]["valid_session"] == "2026-09-04"
    context["execution"]["decisions"][0]["account_id"] = "foreign-account"
    with pytest.raises(ValueError, match="decision event differs"):
        render_forward_chart_html(context)


def test_pte_forward_chart_rejects_candidate_or_unknown_fields() -> None:
    context = _context()
    context["candidate"] = {"candidate_id": "S007-C0001"}

    with pytest.raises(ValueError, match="fields are invalid"):
        render_forward_chart_html(context)


@pytest.mark.parametrize('field,value', [('account_id','foreign-account'),('symbol','159326.SZ')])
def test_forward_chart_rejects_foreign_observation(field,value):
    context = _context()
    context['observations'][0][field] = value
    with pytest.raises(ValueError, match='differs'):
        render_forward_chart_html(context)


def test_forward_chart_uses_account_symbol_and_values_without_strategy_package_identity():
    context = _context()
    context['strategy']['release_id'] = 'S999-v7'
    context['strategy']['release_hash'] = 'different-package'
    context['strategy']['strategy_id'] = 'S999'
    html = render_forward_chart_html(context)
    assert '基础分' in html

    context['observations'][0]['observation']['series'][0]['value'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        render_forward_chart_html(context)


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


def test_signal_snapshot_survives_account_chart_projection_without_changing_event_facts():
    from paper_trading_engine.account_chart import AccountChartService
    from paper_trading_engine.forward_chart import ChartObservation

    context = _context()
    previous = context["observations"][0]["observation"]
    observation = {
        **previous, "contract_version": "strategy_observation.v3",
        "strategy": {"strategy_id": "S007", "reference_id": "S007-v1", "release_hash": "a" * 64,
                     "runtime_sha256": "b" * 64, "symbol": "588080.SH"},
        "definition_sha256": "c" * 64, "signal_identity": "d" * 64, "plan_identity": "e" * 64,
        "signal_date": "2026-09-03", "valid_session": "2026-09-04", "action": "WAIT",
        "target_position": 0.0, "signal_panel": _signal_panel(),
    }
    row = {**context["observations"][0], "payload": {
        "observation": observation, "symbol": "588080.SH", "action": "WAIT", "target_quantity": 0,
    }}
    projected = AccountChartService._decision(row)
    chart = ChartObservation.from_dict(projected["observation"])
    assert chart.to_dict()["series"] == previous["series"]
    assert chart.to_dict()["facts"] == previous["facts"]
    assert chart.to_dict()["signal_panel"] == _signal_panel()
    assert chart.definition_sha256 == "c" * 64 and chart.release_hash == "a" * 64
    context["observations"] = [projected]
    html = render_forward_chart_html(context)
    payload = json.loads(re.search(r'<script id="forward-context" type="application/json">(.*?)</script>', html).group(1))
    assert payload["observations"][0]["observation"] == projected["observation"]
    assert payload["execution"] == context["execution"]
    assert payload["market_data"] == context["market_data"]

    observation["contract_version"] = "strategy_observation.v99"
    with pytest.raises(ValueError, match="unsupported"):
        AccountChartService._decision(row)


@pytest.mark.parametrize("mutation", ["missing_identity", "unknown_field", "invalid_state", "inactive_value"])
def test_signal_chart_rejects_malformed_enhanced_snapshots(mutation):
    context = _context()
    observation = context["observations"][0]["observation"]
    observation.update(signal_panel=_signal_panel(), definition_sha256="c" * 64, release_hash="a" * 64)
    if mutation == "missing_identity":
        del observation["definition_sha256"]
    elif mutation == "unknown_field":
        observation["signal_panel"]["renderer_options"] = {}
    elif mutation == "invalid_state":
        observation["signal_panel"]["states"][0]["value"] = "unknown"
    else:
        observation["signal_panel"]["series"][0]["value"] = 0
    with pytest.raises(ValueError):
        render_forward_chart_html(context)


def test_unavailable_v3_observation_preserves_reason_without_values():
    from paper_trading_engine.account_chart import AccountChartService
    from paper_trading_engine.forward_chart import ChartObservation

    context = _context()
    failure = {"contract_version": "strategy_observation.v3", "status": "UNAVAILABLE",
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
    for invalid in ({"status": "UNAVAILABLE", "message": ""},
                    {"status": "UNAVAILABLE", "message": "failure", "series": []}):
        with pytest.raises(ValueError):
            ChartObservation.from_dict(invalid)
    failure["contract_version"] = "strategy_observation.v2"
    assert not AccountChartService._has_chart_observation(row)
