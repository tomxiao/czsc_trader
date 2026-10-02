"""Synthetic S008 example for the public research-experiment contract."""

from __future__ import annotations

from datetime import date
import json

from dataflows import DataRequest

from research_experiment import (
    ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition, ExperimentDataScope,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


class Experiment(ResearchExperiment):
    """Demonstrate a bounded discovery experiment without real market returns."""

    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=2,
            experiment_id="20260924_S008_EX99",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            research_question="Can a small synthetic price sample exercise the anchor contract?",
            hypothesis="The declared sample is readable and produces one deterministic summary.",
            falsification_conditions=("DFLS does not return the declared sample",),
            development_cutoff=date(2026, 9, 2),
            random_seed=8008,
            allowed_datasets=("etf.ohlcv",),
            subjects=("518880.SH",),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=(
                    "A deterministic price sample can validate the REX execution boundary",
                ),
                information_paths=(
                    "DFLS price publication -> deterministic summary facts",
                ),
                stage_objectives=(
                    "Validate the S008 prototype experiment contract end to end",
                ),
                observation_metrics=("row count", "mean close", "worker budget"),
                methodology=(
                    "Fetch the declared sample and write one hash-registered summary",
                ),
            ),
            dependencies=(ExperimentDependency("czsc-dataflows", "0.1.0"),),
            capabilities=ExperimentCapabilities(searches_parameters=True),
        )

    def synthetic_precheck(self):
        assert self.definition.subjects == ("518880.SH",)

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.SEARCH_PARAMETERS)
        publication = context.data.fetch(
            DataRequest(
                dataset="etf.ohlcv",
                symbol="518880.SH",
                start="2026-09-01",
                end="2026-09-02",
                required_cutoff="2026-09-02",
            )
        )
        summary = {
            "rows": int(len(publication.dataframe)),
            "mean_close": float(publication.dataframe["Close"].mean()),
            "max_workers": context.resources.max_workers,
        }
        output = context.workspace.path("summary.json")
        output.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        artifact = context.workspace.register_artifact("summary.json", "research-summary")
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts=summary,
            diagnostics={"synthetic": True},
            artifacts=(artifact,),
        )
