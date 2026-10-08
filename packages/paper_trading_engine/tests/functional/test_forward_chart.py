from __future__ import annotations

import json
import re

import pytest

from paper_trading_engine.forward_chart import render_forward_chart_html


def _context() -> dict[str, object]:
    return {
        "contract_version": "pte_forward_chart.v1",
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
                "decision_id": "DEC-1",
                "signal_date": "2026-09-03",
                "valid_session": "2026-09-04",
                "generated_at": "2026-09-03T12:00:00+00:00",
                "action": "BUY",
                "target_quantity": 1000,
                "observation": {
                    "contract_version": "strategy_observation.v2",
                    "strategy": {"strategy_id":"S007", "reference_id":"S007-v1", "release_hash":"a"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH"},
                    "definition_sha256":"d"*64, "signal_identity":"e"*64, "plan_identity":"f"*64,
                    "signal_date":"2026-09-03", "valid_session":"2026-09-04", "facts":[],
                    "status": "READY",
                    "action": "BUY",
                    "target_position": 1.0,
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


@pytest.mark.parametrize('field,value', [('release_hash','0'*64),('reference_id','S999-v1'),('symbol','159326.SZ')])
def test_forward_chart_rejects_foreign_observation(field,value):
    context = _context()
    context['observations'][0]['observation']['strategy'][field] = value
    expected = 'reference_id must identify' if field == 'reference_id' else 'differs'
    with pytest.raises(ValueError, match=expected):
        render_forward_chart_html(context)
