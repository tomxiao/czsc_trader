"""Public CLI, API exports and catalog-template collaboration contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from czsc_trader.cli.main import main
from czsc_trader.application import (
    RepositoryContext, ValidationError,
    validate_catalog, list_catalog, show_catalog, validate_templates, list_templates,
    show_template, instantiate_template,
)


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_API = {
    "CandidateInspectionRequest", "InspectionReplay",
    "inspect_candidate", "record_research_decision", "freeze_candidate", "get_freeze_result",
    "assemble_delivery", "validate_delivery", "CandidateRegistrationRequest", "register_candidate",
    "load_candidate", "RepositoryContext", "CommandResult", "CommandError", "ValidationError",
    "create_research_batch", "update_research_intent", "create_research_context", "create_experiment",
    "ResearchBatchRequest", "ResearchIntentUpdate", "ExperimentRequest", "publish_evidence", "validate_catalog", "list_catalog",
    "show_catalog", "validate_templates", "list_templates", "show_template", "instantiate_template",
    "publish_evidence_many",
    "BacktestRequest", "BacktestEvaluation", "run_backtest", "list_installed_strategies", "strategy_info", "deploy_strategy",
    "validate_release_package",
}


def test_cli_loads_dotenv_without_overriding_process_environment(minimal_repo, monkeypatch, capsys):
    (minimal_repo / ".env").write_text(
        "TUSHARE_TOKEN=repository-token\nSRT_TEST_SETTING=repository-value\n", encoding="utf-8",
    )
    monkeypatch.setenv("TUSHARE_TOKEN", "process-token")
    monkeypatch.delenv("SRT_TEST_SETTING", raising=False)
    monkeypatch.chdir(minimal_repo)
    assert main(["backtest", "run", "--strategy", "S900", "--strategy-version", "v1",
                 "--symbol", "588080.SH", "--asset", "etf", "--start", "2026-01-01",
                 "--end", "2026-01-02", "--init-cash", "100000", "--lot-size", "100"]) != 0
    error = json.loads(capsys.readouterr().out)
    assert error["error"]["code"] == "backtest_strategy_invalid"
    assert os.environ["TUSHARE_TOKEN"] == "process-token"
    assert os.environ["SRT_TEST_SETTING"] == "repository-value"


def test_installed_cli_exposes_supported_command_surface():
    executable = Path(sys.executable).with_name("czsc-trader.exe" if sys.platform == "win32" else "czsc-trader")
    for arguments, expected in [(('--help',), '{backtest}'),
                                (('backtest', '--help'), '{run}'),
                                (('backtest', 'run', '--help'), '--strategy-version')]:
        result = subprocess.run([str(executable), *arguments], check=False, capture_output=True,
                                text=True, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert expected in result.stdout
        if arguments == ('backtest', 'run', '--help'):
            assert "--outputs-root" in result.stdout
            assert "--candidate-id" in result.stdout
        assert "--repo-root" not in result.stdout


def test_removed_cli_commands_return_invalid_arguments(capsys):
    for command in ("data", "research", "candidate", "strategy", "experiment", "archive",
                    "news", "catalog", "template"):
        assert main([command, "--format", "json"]) != 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "FAIL"
        assert result["error"]["code"] == "invalid_arguments"


def test_public_business_api_is_explicit_and_importable():
    import czsc_trader.application as api
    assert set(api.__all__) == PUBLIC_API
    for name in PUBLIC_API:
        assert callable(getattr(api, name)), name
    with pytest.raises(AttributeError):
        getattr(api, "extract_news")


@pytest.fixture
def catalog_context(minimal_repo):
    # Two real canonical definitions suffice for FSC-STC collaboration; no research input.
    family_document = json.loads((ROOT / "catalog/information_families.json").read_text(encoding="utf-8"))
    family_document["items"] = [x for x in family_document["items"]
                                if x["family_id"] in {"POSITION_VALUATION", "MARKET_STRUCTURE"}]
    for relative, document in [("information_families.json", family_document)]:
        path = minimal_repo / "catalog" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    for kind, identity in [("factors", "F-PROJECT-ETF-NAV-PREMIUM"),
                           ("signals", "SIG-CZSC-cxt_bi_base_V230228")]:
        document = json.loads((ROOT / f"catalog/{kind}/definitions.json").read_text(encoding="utf-8"))
        key = "factor_id" if kind == "factors" else "signal_id"
        item = next(x for x in document["items"] if x[key] == identity)
        if kind == "signals":
            item["states"] = ["满足", "不满足"]
        path = minimal_repo / f"catalog/{kind}/definitions.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 1, "items": [item]}, ensure_ascii=False), encoding="utf-8")
    templates = minimal_repo / "strategy_templates"
    templates.mkdir()
    shutil.copyfile(ROOT / "strategy_templates/templates.json", templates / "templates.json")
    return RepositoryContext.discover(minimal_repo)


def test_catalog_public_results_preserve_filter_and_snapshot_identity(catalog_context):
    validated = validate_catalog(catalog_context)
    selected = list_catalog(catalog_context, kind="factor", family="POSITION_VALUATION", status="DISCOVERED", query="nav-premium")
    shown = show_catalog(catalog_context, "F-PROJECT-ETF-NAV-PREMIUM")
    assert (validated.status, validated.command) == ("PASS", "catalog.validate")
    assert (validated.result["families"], validated.result["factors"], validated.result["signals"]) == (2, 1, 1)
    assert selected.command == "catalog.list" and selected.result["count"] == 1
    assert [x["id"] for x in selected.result["definitions"]] == ["F-PROJECT-ETF-NAV-PREMIUM"]
    assert shown.command == "catalog.show" and shown.result["definition"]["factor_id"] == "F-PROJECT-ETF-NAV-PREMIUM"
    assert selected.result["digest"] == shown.result["digest"] == validated.result["digest"]
    assert len(validated.result["digest"]) == 64
    empty = list_catalog(catalog_context, kind="factor", family=None, status=None, query="missing")
    assert empty.status == "PASS" and empty.result["count"] == 0 and empty.result["definitions"] == ()


@pytest.mark.parametrize("operation,code", [("query", "factor_signal_catalog_query_invalid"),
                                            ("missing", "factor_signal_catalog_not_found")])
def test_catalog_public_errors_have_domain_semantics(catalog_context, operation, code):
    with pytest.raises(ValidationError) as error:
        if operation == "query":
            list_catalog(catalog_context, kind="factor", family="MISSING", status=None, query=None)
        else:
            show_catalog(catalog_context, "F-NOT-FOUND")
    assert error.value.code == code


def _prototype(context, **changes):
    binding = {"slot": "entry_events", "source_id": "SIG-CZSC-cxt_bi_base_V230228",
               "source_kind": "SIGNAL", "state": "满足", "weight": None, **changes}
    path = context.root / "prototype.json"
    path.write_text(json.dumps({"schema_version": 1, "template_id": "STC-T04-EVENT-HOLD",
                               "bindings": [binding], "parameters": {"holding_sessions": 5}},
                              ensure_ascii=False), encoding="utf-8")
    return path


def test_template_public_results_bind_real_catalog_sources(catalog_context):
    validated = validate_templates(catalog_context)
    selected = list_templates(catalog_context, operator="EVENT_HOLD", status="READY", query=None)
    shown = show_template(catalog_context, "STC-T04-EVENT-HOLD")
    assert validated.status == "PASS" and validated.result["templates"] == 5
    assert selected.command == "template.list" and selected.result["count"] == 1
    assert selected.result["templates"][0]["template_id"] == "STC-T04-EVENT-HOLD"
    assert shown.result["template"]["operator"] == "EVENT_HOLD"
    assert selected.result["digest"] == shown.result["digest"] == validated.result["digest"]
    spec = _prototype(catalog_context)
    result = instantiate_template(catalog_context, spec)
    assert result.status == "PASS" and result.command == "template.instantiate"
    assert result.result["catalog_digest"] == validated.result["digest"]
    instance = result.result["instance"]
    assert instance["instance_id"].startswith("STI-")
    assert instance["bindings"][0]["source_id"] == "SIG-CZSC-cxt_bi_base_V230228"
    assert instantiate_template(catalog_context, spec).result == result.result


@pytest.mark.parametrize("operation,code", [("query", "strategy_template_catalog_query_invalid"),
                                            ("missing", "strategy_template_not_found")])
def test_template_public_errors_have_domain_semantics(catalog_context, operation, code):
    with pytest.raises(ValidationError) as error:
        if operation == "query":
            list_templates(catalog_context, operator="MISSING", status=None, query=None)
        else:
            show_template(catalog_context, "STC-NOT-FOUND")
    assert error.value.code == code


@pytest.mark.parametrize("changes", [{"source_id": "SIG-NOT-IN-FSC"},
                                      {"source_id": "F-PROJECT-ETF-NAV-PREMIUM"},
                                      {"state": None}, {"state": "未声明状态"}])
def test_template_instantiation_rejects_invalid_catalog_binding(catalog_context, changes):
    spec = _prototype(catalog_context, **changes)
    before = {p: p.read_bytes() for p in catalog_context.root.rglob("*.json")}
    with pytest.raises(ValidationError) as error:
        instantiate_template(catalog_context, spec)
    assert error.value.code == "strategy_template_binding_invalid"
    assert {p: p.read_bytes() for p in catalog_context.root.rglob("*.json")} == before


def test_template_instantiation_rejects_deprecated_source(catalog_context):
    path = catalog_context.root / "catalog/signals/definitions.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["items"][0]["status"] = "DEPRECATED"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    assert show_catalog(catalog_context, "SIG-CZSC-cxt_bi_base_V230228").status == "PASS"
    with pytest.raises(ValidationError, match="deprecated FSC source") as error:
        instantiate_template(catalog_context, _prototype(catalog_context))
    assert error.value.code == "strategy_template_binding_invalid"
