"""Pre-execution checks for source-bound research experiments."""

from __future__ import annotations

from collections.abc import Callable

from research_experiment import (
    ExperimentInput,
    ExperimentPreflightCheck,
    ExperimentPreflightReport,
    ExperimentPreflightStatus,
    ExperimentResources,
    LoadedExperiment,
    ResearchExperiment,
    experiment_source_sha256,
)

from ..experiment_archive import validate_experiment_manifest_metadata


def _check(
    code: str,
    action: Callable[[], None],
    *,
    success: str,
) -> ExperimentPreflightCheck:
    try:
        action()
    except Exception as exc:
        return ExperimentPreflightCheck(code, ExperimentPreflightStatus.FAIL, str(exc))
    return ExperimentPreflightCheck(code, ExperimentPreflightStatus.PASS, success)


def preflight_experiment(
    experiment: LoadedExperiment,
    *,
    resources: ExperimentResources,
    predecessors: tuple[ExperimentInput, ...] = (),
) -> ExperimentPreflightReport:
    """Run repeatable checks without issuing a receipt or formal artifact."""

    if not isinstance(experiment, LoadedExperiment):
        raise TypeError("experiment must be loaded by load_experiment")
    if not isinstance(resources, ExperimentResources):
        raise TypeError("resources must be ExperimentResources")

    checks: list[ExperimentPreflightCheck] = []

    def source_bound() -> None:
        actual = experiment_source_sha256(experiment.root, experiment.binding.source_files)
        if actual != experiment.binding.source_sha256:
            raise ValueError("experiment source SHA-256 differs from binding")

    checks.append(_check("SOURCE_BOUND", source_bound, success="source closure matches binding"))

    def definition_bound() -> None:
        if experiment.implementation.definition.sha256 != experiment.definition.sha256:
            raise ValueError("experiment definition changed after loading")

    checks.append(_check("DEFINITION_BOUND", definition_bound, success="definition is stable"))

    def resource_contract() -> None:
        if resources.random_seed != experiment.definition.random_seed:
            raise ValueError("resource random_seed must match experiment definition")
        if (
            experiment.definition.capabilities.searches_parameters
            and resources.max_evaluations is None
        ):
            raise ValueError("parameter-search experiments require max_evaluations")

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
        if experiment.binding.schema_version >= 3 and len(subjects) != 1:
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

    explicit_precheck = (
        type(experiment.implementation).synthetic_precheck
        is not ResearchExperiment.synthetic_precheck
    )
    if experiment.binding.schema_version >= 3 and not explicit_precheck:
        checks.append(
            ExperimentPreflightCheck(
                "SYNTHETIC_PRECHECK",
                ExperimentPreflightStatus.FAIL,
                "binding schema v3 requires an explicit synthetic_precheck",
            )
        )
    elif explicit_precheck:
        checks.append(
            _check(
                "SYNTHETIC_PRECHECK",
                experiment.implementation.synthetic_precheck,
                success="synthetic precheck passed",
            )
        )
    else:
        checks.append(
            ExperimentPreflightCheck(
                "SYNTHETIC_PRECHECK",
                ExperimentPreflightStatus.WARNING,
                "legacy binding has no explicit synthetic precheck",
            )
        )

    if experiment.binding.schema_version == 2:
        checks.append(
            ExperimentPreflightCheck(
                "LEGACY_BINDING",
                ExperimentPreflightStatus.WARNING,
                "binding schema v2 is loadable but does not enforce preflight before execution",
            )
        )
    else:
        checks.append(
            ExperimentPreflightCheck(
                "PREFLIGHT_ENFORCEMENT",
                ExperimentPreflightStatus.PASS,
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
