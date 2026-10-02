"""Pre-execution checks for source-bound research experiments."""

from __future__ import annotations

from collections.abc import Callable
import ast
import json

import pandas as pd
from dataflows import Dataflows, DataRequest

from research_experiment import (
    ExperimentInput,
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightReport,
    ExperimentPreflightStatus,
    ExperimentResources,
    LoadedExperiment,
    ResearchExperiment,
    experiment_source_sha256,
)

from ..experiment_archive import validate_experiment_manifest_metadata


def _source_risks(experiment: LoadedExperiment) -> list[ExperimentPreflightCheck]:
    risks: dict[str, list[str]] = {}
    for name in experiment.binding.source_files:
        if not name.endswith(".py"):
            continue
        tree = ast.parse((experiment.root / name).read_text(encoding="utf-8-sig"), filename=name)
        for node in ast.walk(tree):
            code = None
            if isinstance(node, ast.Call):
                function = node.func
                called = (
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else getattr(function, "id", "")
                )
                keywords = {item.arg: item.value for item in node.keywords}
                if called == "to_numpy" and not (
                    isinstance(keywords.get("copy"), ast.Constant)
                    and keywords["copy"].value is True
                ):
                    code = "NUMPY_VIEW_MUTATION_RISK"
                elif (
                    called == "join"
                    and isinstance(function, ast.Attribute)
                    and not isinstance(function.value, ast.Constant)
                    and not {"lsuffix", "rsuffix"} & set(keywords)
                ):
                    code = "JOIN_COLUMN_COLLISION_RISK"
                elif called in {"ProcessPoolExecutor", "Process", "Pool"}:
                    code = "PROCESS_PAYLOAD_REVIEW"
                elif (
                    called == "dict"
                    and node.args
                    and isinstance(node.args[0], ast.Attribute)
                    and node.args[0].attr in {"facts", "diagnostics"}
                ):
                    code = "SHALLOW_RESULT_SERIALIZATION_RISK"
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
                if (
                    node.value.attr == "trials"
                    and isinstance(node.slice, ast.UnaryOp)
                    and isinstance(node.slice.op, ast.USub)
                    and isinstance(node.slice.operand, ast.Constant)
                    and node.slice.operand.value == 1
                ):
                    code = "LAST_TRIAL_IDENTITY_RISK"
            if code:
                risks.setdefault(code, []).append(f"{name}:{node.lineno}")
    guidance = {
        "NUMPY_VIEW_MUTATION_RISK": "to_numpy may return a read-only/shared view; test any in-place mutation",
        "JOIN_COLUMN_COLLISION_RISK": "join has no explicit suffix policy; test overlapping columns",
        "PROCESS_PAYLOAD_REVIEW": "test worker payload serialization and child-process data configuration",
        "SHALLOW_RESULT_SERIALIZATION_RISK": "dict(facts/diagnostics) leaves nested immutable mappings; use result.to_dict()",
        "LAST_TRIAL_IDENTITY_RISK": "trials[-1] may identify a queued trial; retain the trial returned by ask()",
    }
    return [
        ExperimentPreflightCheck(
            code, ExperimentPreflightStatus.WARNING, f"{guidance[code]}: {', '.join(locations[:8])}"
        )
        for code, locations in sorted(risks.items())
    ]


def _check(
    code: str,
    action: Callable[[], None],
    *,
    success: str,
) -> ExperimentPreflightCheck:
    try:
        action()
    except Exception as exc:
        return ExperimentPreflightCheck(
            code, ExperimentPreflightStatus.FAIL, str(exc) or type(exc).__name__
        )
    return ExperimentPreflightCheck(code, ExperimentPreflightStatus.PASS, success)


def preflight_experiment(
    experiment: LoadedExperiment,
    *,
    resources: ExperimentResources,
    predecessors: tuple[ExperimentInput, ...] = (),
    dataflows: Dataflows | None = None,
    data_requests: tuple[DataRequest, ...] = (),
) -> ExperimentPreflightReport:
    """Run repeatable checks without issuing a receipt or formal artifact."""

    if not isinstance(experiment, LoadedExperiment):
        raise TypeError("experiment must be loaded by load_experiment")
    if not isinstance(resources, ExperimentResources):
        raise TypeError("resources must be ExperimentResources")
    if dataflows is not None and not isinstance(dataflows, Dataflows):
        raise TypeError("dataflows must be Dataflows or None")
    if not isinstance(data_requests, tuple) or not all(
        isinstance(item, DataRequest) for item in data_requests
    ):
        raise TypeError("data_requests must be a tuple of DataRequest values")
    if data_requests and dataflows is None:
        raise ValueError("explicit data requests require a configured Dataflows")

    checks: list[ExperimentPreflightCheck] = []

    def source_bound() -> None:
        actual = experiment_source_sha256(experiment.root, experiment.binding.source_files)
        if actual != experiment.binding.source_sha256:
            raise ValueError("experiment source SHA-256 differs from binding")

    checks.append(_check("SOURCE_BOUND", source_bound, success="source closure matches binding"))

    def definition_bound() -> None:
        if experiment.definition.schema_version != 2:
            raise ValueError("new executions require experiment definition schema 2")
        if experiment.implementation.definition.sha256 != experiment.definition.sha256:
            raise ValueError("experiment definition changed after loading")

    checks.append(_check("DEFINITION_BOUND", definition_bound, success="definition is stable"))

    def resource_contract() -> None:
        if resources.random_seed != experiment.definition.random_seed:
            raise ValueError("resource random_seed must match experiment definition")

    checks.append(
        _check("RESOURCE_CONTRACT", resource_contract, success="resources match definition")
    )

    def predecessor_contract() -> None:
        items = tuple(predecessors)
        if not all(isinstance(item, ExperimentInput) for item in items):
            raise TypeError("predecessors must contain ExperimentInput values")
        actual = [item.experiment_id for item in items]
        if len(actual) != len(set(actual)):
            raise ValueError("predecessor inputs must be unique")
        expected = set(experiment.definition.protocol.predecessor_experiment_ids)
        if set(actual) != expected:
            raise ValueError("predecessor inputs differ from experiment protocol")

    checks.append(
        _check("PREDECESSOR_CONTRACT", predecessor_contract, success="predecessor identities match")
    )

    def archive_identity() -> None:
        subjects = experiment.definition.subjects
        if len(subjects) != 1:
            raise ValueError("binding schema v3 requires exactly one experiment subject")
        if subjects:
            validate_experiment_manifest_metadata(
                experiment.root,
                {
                    "experiment_id": experiment.definition.experiment_id,
                    "strategy_id": experiment.definition.strategy_id,
                    "symbol": subjects[0],
                    "development_cutoff": experiment.definition.development_cutoff.isoformat(),
                },
            )

    checks.append(
        _check("ARCHIVE_IDENTITY", archive_identity, success="static archive identity is valid")
    )

    def source_risks() -> None:
        checks.extend(_source_risks(experiment))

    checks.append(
        _check(
            "SOURCE_RISK_SCAN",
            source_risks,
            success="known source patterns inspected; warnings require review",
        )
    )

    for index, request in enumerate(data_requests, 1):

        def data_ready(request=request) -> None:
            if any(item.status is ExperimentPreflightStatus.FAIL for item in checks):
                raise ValueError("data probe skipped because prerequisite checks failed")
            definition = experiment.definition
            if request.dataset not in definition.allowed_datasets:
                raise PermissionError("preflight dataset was not declared")
            if not definition.capabilities.reads_real_returns:
                raise PermissionError("data readiness probe requires reads_real_returns capability")
            if pd.Timestamp(request.end).date() > definition.development_cutoff:
                raise PermissionError("preflight request exceeds development cutoff")
            result = dataflows.fetch(request)
            if not result.ready:
                raise ValueError(
                    f"{request.dataset}: {result.status.value}/{result.error.code}: {result.error.message}"
                )

        checks.append(
            _check(
                f"DATA_REQUEST_{index:03d}",
                data_ready,
                success=f"{request.dataset} request is READY",
            )
        )
    if not data_requests:
        checks.append(
            ExperimentPreflightCheck(
                "DATA_READINESS",
                ExperimentPreflightStatus.WARNING,
                "no explicit data requests supplied; credentials, availability and coverage were not probed",
            )
        )

    explicit_precheck = (
        type(experiment.implementation).synthetic_precheck
        is not ResearchExperiment.synthetic_precheck
    )
    if any(item.status is ExperimentPreflightStatus.FAIL for item in checks):
        checks.append(
            ExperimentPreflightCheck(
                "SYNTHETIC_PRECHECK",
                ExperimentPreflightStatus.FAIL,
                "synthetic execution skipped because prerequisite checks failed",
            )
        )
    elif not explicit_precheck:
        checks.append(
            ExperimentPreflightCheck(
                "SYNTHETIC_PRECHECK",
                ExperimentPreflightStatus.FAIL,
                "binding schema v3 requires an explicit synthetic_precheck",
            )
        )
    elif explicit_precheck:

        def synthetic() -> None:
            result = experiment.implementation.synthetic_precheck()
            if result is None:
                checks.append(
                    ExperimentPreflightCheck(
                        "SYNTHETIC_COVERAGE",
                        ExperimentPreflightStatus.WARNING,
                        "assertion-only precheck provides no named coverage or output serialization sample",
                    )
                )
                return
            if not isinstance(result, ExperimentPrecheckResult):
                raise TypeError("synthetic_precheck must return ExperimentPrecheckResult or None")
            checks.extend(
                ExperimentPreflightCheck(f"SYNTHETIC_{item.code}", item.status, item.message)
                for item in result.checks
            )
            if any(item.status is ExperimentPreflightStatus.FAIL for item in result.checks):
                raise ValueError("one or more named synthetic checks failed")
            if result.result is None:
                checks.append(
                    ExperimentPreflightCheck(
                        "RESULT_SERIALIZATION",
                        ExperimentPreflightStatus.WARNING,
                        "no synthetic ExperimentResult sample supplied",
                    )
                )
            else:

                def serialize() -> None:
                    payload = result.result.to_dict()
                    if json.loads(json.dumps(payload, allow_nan=False)) != payload:
                        raise ValueError("synthetic result differs after JSON roundtrip")

                serialized = _check(
                    "RESULT_SERIALIZATION",
                    serialize,
                    success="synthetic output JSON roundtrip passed",
                )
                checks.append(serialized)
                if serialized.status is ExperimentPreflightStatus.FAIL:
                    raise ValueError("synthetic output serialization failed")

        checks.append(
            _check(
                "SYNTHETIC_PRECHECK",
                synthetic,
                success="synthetic precheck passed",
            )
        )
        checks.append(
            _check(
                "SOURCE_UNCHANGED",
                source_bound,
                success="source unchanged after synthetic precheck",
            )
        )
        checks.append(
            _check(
                "DEFINITION_UNCHANGED",
                definition_bound,
                success="definition unchanged after synthetic precheck",
            )
        )
    checks.append(
        ExperimentPreflightCheck(
            "PREFLIGHT_ENFORCEMENT", ExperimentPreflightStatus.PASS,
            "binding schema v3 requires preflight at execution entry",
        )
    )

    return ExperimentPreflightReport(
        experiment_id=experiment.definition.experiment_id,
        definition_sha256=experiment.definition.sha256,
        source_sha256=experiment.binding.source_sha256,
        resources_sha256=resources.sha256,
        checks=tuple(checks),
    )


__all__ = ["preflight_experiment"]
