"""Small caller-owned inputs for public evaluation and backtest tests."""
from pathlib import Path
import json
import re

import pandas as pd
from strategy_runtime import StrategyCandidate, StrategyRuntime
from dataflows import DataSpace
from czsc_trader.research_tools.context import ResearchContext, ResearchBatchRef
from czsc_trader.research_tools.evaluation_access import EvaluationAccess

from czsc_trader.application import RepositoryContext
from czsc_trader.research_tools import (
    EvaluationBenchmark, EvaluationCost, EvaluationRequest, EvaluationWindow, NextOpenBuyHold,
)
from test_candidate_runtime_execution import _install_candidate_dataflows


def request_for_prices(candidate_payload, root, monkeypatch, prices, *, start_index=1,
                       initial_cash=100_000, benchmark=None, flow=None, cost=.001, hfq_factors=None):
    payload, source = candidate_payload
    if flow is None:
        flow = [0.1] * len(prices)
    features = pd.DataFrame({"Date": prices["dt"], "Flow": flow})
    flows = _install_candidate_dataflows(monkeypatch, features, prices, base_dir=root,
        space=DataSpace(Path("research/S900/assets/data")), hfq_factors=hfq_factors)
    marker = Path(root) / "pyproject.toml"
    if not marker.exists():
        (Path(root) / "src/czsc_trader").mkdir(parents=True, exist_ok=True)
        marker.write_text("[project]\nname='public-backtest-test'\n", encoding="utf-8")
    repository = RepositoryContext.discover(root, explicit_root=root)
    context = ResearchContext(ResearchBatchRef("S900"), repository, flows, StrategyRuntime(dataflows=flows),
                              EvaluationAccess(dataflows=flows, strategy_id="S900"))
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    request = EvaluationRequest(
        root, "synthetic", candidate,
        {"candidate_id": candidate.reference_id,
         "source_files": payload["runtime"]["source_files"],
         "implementation_sha256": payload["runtime"]["source_sha256"]},
        "588080.SH", "etf",
        (EvaluationWindow("full", prices["dt"].iloc[start_index].date(),
                          prices["dt"].iloc[-1].date()),),
        prices["dt"].iloc[-1].date(), initial_cash, (EvaluationCost("cost", cost),),
        benchmark=benchmark or EvaluationBenchmark(NextOpenBuyHold(100)),
    )
    return context, request, flows


def chart_payload(html):
    match = re.search(r'<script id="forward-context" type="application/json">(.*?)</script>', html, re.S)
    assert match is not None
    return json.loads(match[1])


def assert_public_charts(output):
    """Cross-check rendered public facts against their published source ledgers."""
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    observations = json.loads((output / "observations.json").read_text(encoding="utf-8"))
    decisions = pd.read_csv(output / "decisions.csv")
    fills = pd.read_csv(output / "fills.csv")
    account = pd.read_csv(output / "account_daily.csv")
    for name in ("chart.html", "ma_chart.html"):
        html = (output / name).read_text(encoding="utf-8")
        payload = chart_payload(html)
        assert "<script src=" not in html and "Plotly.newPlot" not in html
        assert 'data-range="all" aria-pressed="true"' in html
        assert all(f'data-layer="{layer}"' in html for layer in ("signal", "fill", "position"))
        assert set(payload["metrics"]) == {"return", "max_drawdown", "closed_trades", "calmar", "win_loss_ratio", "win_rate"}
        expected = metrics["strategy"]["metrics"] if name == "chart.html" else metrics["benchmarks"]["ma5_ma20"]["metrics"]
        assert payload["metrics"] == {key: expected[key] for key in payload["metrics"]}
        if expected["closed_trades"] == 0:
            assert '<span>交易胜率</span><strong>N/A</strong>' in html
        if expected["calmar"] is None:
            assert '<span>卡玛比率</span><strong>N/A</strong>' in html
        if name == "chart.html":
            assert len(payload["observations"]) == len(observations) == len(decisions) > 0
            assert [row["signal_date"] for row in payload["observations"]] == decisions.signal_date.tolist()
            assert [row["valid_session"] for row in payload["observations"]] == decisions.valid_session.tolist()
            assert [row["observation"]["series"] for row in payload["observations"]] == [row["series"] for row in observations]
            expected_fills = fills
            expected_account = account
        else:
            expected_fills = pd.read_csv(output / "ma_orders.csv")
            expected_account = pd.read_csv(output / "ma_account_daily.csv")
        assert len(payload["execution"]["fills"]) == len(expected_fills)
        assert len(payload["execution"]["snapshots"]) == len(expected_account) > 0
        assert [row["quantity"] for row in payload["execution"]["snapshots"]] == expected_account.quantity.tolist()
        for row, fact in zip(payload["execution"]["fills"], expected_fills.to_dict("records"), strict=True):
            assert row["price"] == fact["price"]
            assert row["session"] == str(fact.get("fill_time", fact.get("time", fact.get("execution_date"))))[:10]
        assert all(row["signal_date"] < row["valid_session"] for row in payload["observations"])
    return chart_payload((output / "chart.html").read_text(encoding="utf-8"))


def research_context(repository, flows, strategy_id="S900"):
    return ResearchContext(ResearchBatchRef(strategy_id), repository, flows,
                           StrategyRuntime(repository.strategy_root, dataflows=flows),
                           EvaluationAccess(dataflows=flows, strategy_id=strategy_id))


def render_output(evaluation, repository_root):
    from czsc_trader.backtesting.service import _backtest_report_files
    from czsc_trader.temp_workspace import create_temporary_directory
    output = create_temporary_directory(repository_root, "backtest-report-tests")
    for name, content in _backtest_report_files(evaluation).items():
        (output / name).write_bytes(content)
    return output


def publish_reports(context, evaluation):
    from czsc_trader.application import create_experiment, publish_evidence
    from czsc_trader.application.research_governance_service import ExperimentRequest
    from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
    from czsc_trader.backtesting.service import _backtest_report_files
    experiment = create_experiment(context, ExperimentRequest("Backtest", "Inspect account results", evaluation.request.end))
    media = {"html": "text/html", "md": "text/markdown", "json": "application/json", "csv": "text/csv"}
    return {name: publish_evidence(context, MaterialEvidenceWrite(experiment, name, content,
                    media[name.rsplit(".", 1)[1]], name.rsplit(".", 1)[1]))
            for name, content in _backtest_report_files(evaluation).items()}
