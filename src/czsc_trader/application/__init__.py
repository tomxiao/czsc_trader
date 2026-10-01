"""Public business APIs; the user CLI exposes only backtesting.

Lazy exports keep low-level replay/context imports independent of application
services. Every name resolves to the existing implementation, without wrappers.
"""

from importlib import import_module

_EXPORTS = {
    "CandidateInspectionRequest": "inspection_service",
    "InspectionReplay": "inspection_service",
    "inspect_candidate": "inspection_service",
    "record_research_decision": "inspection_service",
    "freeze_candidate": "inspection_service",
    "get_freeze_result": "inspection_service",
    "assemble_delivery": "delivery_service",
    "validate_delivery": "delivery_service",
    "CandidateRegistrationRequest": "candidate_service",
    "register_candidate": "candidate_service",
    "load_candidate": "candidate_service",
    "RepositoryContext": "context",
    "CommandResult": "results",
    "CommandError": "errors",
    "ValidationError": "errors",
    "PrepareDataCommand": "data_service",
    "prepare_data": "data_service",
    "validate_data": "data_service",
    "create_research_batch": "research_governance_service",
    "update_research_intent": "research_governance_service",
    "evaluate_research_request": "research_evaluation_service",
    "PredecessorEvidence": "experiment_service",
    "preflight_experiment_archive": "experiment_service",
    "validate_archives": "archive_service",
    "validate_catalog": "catalog_service",
    "list_catalog": "catalog_service",
    "show_catalog": "catalog_service",
    "validate_templates": "template_service",
    "list_templates": "template_service",
    "show_template": "template_service",
    "instantiate_template": "template_service",
    "BacktestRequestV2": "backtest_service",
    "run_backtest": "backtest_service",
    "list_installed_strategies": "strategy_runtime_service",
    "strategy_info": "strategy_runtime_service",
    "deploy_strategy": "strategy_runtime_service",
    "validate_release_package": "strategy_runtime_service",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"{__name__!r} has no public API {name!r}")
    value = getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
