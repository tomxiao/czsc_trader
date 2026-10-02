"""Complete fixed S011 diagnostic coverage through managed public APIs."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import optuna
from dataflows import Dataset
from research_experiment import (
    ResearchExperiment,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentDataScope,
    ExperimentStage,
    ExperimentProtocol,
    ExperimentDependency,
    ExperimentCapabilities,
    ExperimentResult,
    ExperimentOutcome,
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
)
from strategy_runtime import (
    StrategyCandidate,
    StrategyRuntime,
    ImplementationDependency,
    canonical_sha256,
)
from strategy_manager import (
    CandidateKey,
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
    CandidateRegistrationOrigin,
)
from czsc_trader.application import (
    RepositoryContext,
    load_candidate,
    register_candidate,
    CandidateRegistrationRequest,
)
from czsc_trader.research_tools import (
    build_assessment_evidence,
    EvaluationRequest,
    EvaluationWindow,
    EvaluationCost,
    EvaluationLineage,
    EvaluationBenchmark,
)
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from .family_statistics import historical_accounts, expanded_family_statistics

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
ID = ROOT.name
INPUTS = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
DEPS = tuple(ImplementationDependency(**x) for x in INPUTS["dependencies"])
BENCHMARK = EvaluationBenchmark.from_dict(INPUTS["benchmark"])
START, CUTOFF = date(2025, 2, 6), date(2026, 9, 28)


def child_candidate(spec, parent):
    payload = json.loads(json.dumps(dict(parent.payload), default=dict))
    payload["parameters"] = spec["parameters"]
    return StrategyCandidate("S011", spec["candidate_id"], payload, parent.source_root)


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2,
            experiment_id=ID,
            strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            development_cutoff=CUTOFF,
            random_seed=20261001,
            research_question="What changes when all 36 centers have the declared diagnostics and the search family is updated?",
            hypothesis="Missing diagnostic coverage can be completed without changing center identities or economic targets.",
            falsification_conditions=(
                "A center identity or protocol changes",
                "Any declared diagnostic slot lacks an explained outcome",
            ),
            allowed_datasets=tuple(
                x.value
                for x in (
                    Dataset.ETF_OHLCV,
                    Dataset.ETF_UNADJUSTED_DAILY,
                    Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,
                    Dataset.GLOBAL_INDEX_DAILY,
                    Dataset.TRADING_CALENDAR,
                )
            ),
            subjects=("159326.SZ",),
            dependencies=tuple(ExperimentDependency(**x) for x in INPUTS["dependencies"]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(
                ExperimentStage.ROBUSTNESS,
                ("Coverage completion does not remove selection bias",),
                (
                    "DFLS through formal context, fixed SRT candidates, TDR accounts and SE diagnostics",
                ),
                (
                    "512 fixed joint slots and missing same-source pressure; component completeness audit",
                ),
                ("Joint degradation, stress loss, updated family uncertainty",),
                (
                    "Fixed Optuna queue, one formal owner, sequential evaluation, no retry or adaptive search",
                ),
                tuple(INPUTS["predecessors"]),
            ),
        )

    def synthetic_precheck(self):
        repository = RepositoryContext.discover(REPO)
        parents = {
            x["config_id"]: load_candidate(repository, CandidateKey("S011", x["candidate_id"]))
            for x in INPUTS["centers"]
        }
        runtime = StrategyRuntime()
        groups = {}
        for spec in INPUTS["neighbors"]:
            item = child_candidate(spec, parents[spec["center_config_id"]])
            runtime.describe(item)
            groups.setdefault(spec["center_config_id"], []).append(spec)
            assert (
                item.payload["parameters"]["max_days"]
                == parents[spec["center_config_id"]].payload["parameters"]["max_days"]
            )
        assert len(groups) == 32 and len(INPUTS["neighbors"]) == 512
        for specs in groups.values():
            assert len(specs) == len({canonical_sha256(x["parameters"]) for x in specs}) == 16
            offsets = np.asarray([x["offset"][:6] for x in specs])
            if specs[0]["center_config_id"] == "S011-CFG-000137":
                assert set(offsets[:, 4]) == {-1, 0}
                assert offsets[:, 4].sum() == -8
                symmetric = offsets[:, [0, 1, 2, 3, 5]]
                assert np.array_equal(symmetric.sum(axis=0), np.zeros(5))
                assert np.array_equal(symmetric.T @ symmetric, 16 * np.eye(5))
            else:
                assert np.array_equal(offsets.sum(axis=0), np.zeros(6))
                assert np.array_equal(offsets.T @ offsets, 16 * np.eye(6))
        study = optuna.create_study(storage=optuna.storages.InMemoryStorage())
        for i in range(3):
            study.enqueue_trial({"slot": i})
        for i in range(3):
            trial = study.ask()
            assert trial.suggest_int("slot", 0, 2) == i
            study.tell(trial, float(i))
        assert all(t.state is optuna.trial.TrialState.COMPLETE for t in study.trials)
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "FIXED_DESIGN",
                    ExperimentPreflightStatus.PASS,
                    "512 legal candidates, 31 symmetric designs plus one explicitly bounded design, retained hold periods, Optuna FIFO terminal states",
                ),
            ),
            ExperimentResult(ExperimentOutcome.PASS, {"synthetic_only": True}, {}),
        )

    def execute(self, context):
        for name, digest in INPUTS["historical_sources"].items():
            assert sha256((REPO / name).read_bytes()).hexdigest() == digest, name
        # Validate historical reused accounts before calculating new outcomes.
        historical, historical_audit = historical_accounts(REPO, INPUTS)
        artifacts, results, new_returns = [], [], []

        def save(name, value):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "S011-coverage-evidence"))

        save("historical_account_audit.json", historical_audit)
        repository = RepositoryContext.discover(REPO)
        parents = {
            x["config_id"]: load_candidate(repository, CandidateKey("S011", x["candidate_id"]))
            for x in INPUTS["centers"]
        }
        data = prepare_backtest_execution_data(
            srt_data_root=REPO / ".tmp/s011-completion/execution",
            symbol="159326.SZ",
            asset_type="etf",
            start=START,
            end=CUTOFF,
            dataflows=context.data,
        )
        assert len(data.evaluation_sessions) == 403
        origin = CandidateRegistrationOrigin(
            ID,
            self.definition.sha256,
            sha256((ROOT / "experiment_binding.json").read_bytes()).hexdigest(),
            CandidateEvidence(
                (ROOT / "preflight.json").relative_to(REPO).as_posix(),
                sha256((ROOT / "preflight.json").read_bytes()).hexdigest(),
            ),
        )

        def evaluate(item, costs, relation=None):
            request = EvaluationRequest(
                repository_root=REPO,
                experiment_id=ID,
                strategy=item,
                runtime_binding={
                    "candidate_id": item.reference_id,
                    "source_files": list(item.payload["runtime"]["source_files"]),
                    "implementation_sha256": item.payload["runtime"]["source_sha256"],
                },
                symbol="159326.SZ",
                asset_type="etf",
                windows=(EvaluationWindow("full", START, CUTOFF),),
                data_cutoff=CUTOFF,
                initial_cash=1e6,
                costs=costs,
                execution_data=data,
                benchmark=BENCHMARK,
                workers=1,
                frequency_window_days=60,
                dependencies=DEPS,
                lineage=None if relation is None else EvaluationLineage(relation),
            )
            result = context.evaluation.evaluate(request)
            evidence = build_assessment_evidence(request, result)
            save(f"assessment/{item.candidate_id}.json", [x.to_dict() for x in evidence])
            for run in result.runs:
                account = run.execution.account_daily
                assert np.allclose(
                    account.cash + account.quantity * account.close,
                    account.equity,
                    rtol=0,
                    atol=1e-6,
                )
                assert account.quantity.mod(100).eq(0).all() and account.cash.ge(-1e-6).all()
                if run.scenario_id == "standard":
                    equity = account.equity.to_numpy(float)
                    new_returns.append((item.reference_id, equity / np.r_[1e6, equity[:-1]] - 1))
            results.append(
                {
                    "candidate_id": item.reference_id,
                    "attempt_id": result.attempt_id,
                    "evaluation_ids": [x.identity.evaluation_id for x in result.runs],
                    "parent": None if relation is None else relation.parent.to_dict(),
                }
            )
            print(
                json.dumps({"complete": len(results), "candidate": item.reference_id}), flush=True
            )
            return result

        evaluate(parents["S011-CFG-000193"], (EvaluationCost("fee_20bp", 0.002, "STRESS"),))
        study = optuna.create_study(
            storage=optuna.storages.InMemoryStorage(),
            sampler=optuna.samplers.RandomSampler(seed=20261001),
        )
        for spec in INPUTS["neighbors"]:
            study.enqueue_trial({"slot": spec["design_slot"]})
        for slot, spec in enumerate(INPUTS["neighbors"]):
            trial = study.ask()
            assert trial.suggest_int("slot", 0, 511) == slot
            parent = parents[spec["center_config_id"]]
            item = child_candidate(spec, parent)
            record = INPUTS["parent_records"][parent.reference_id]
            proof = (
                REPO
                / "experiments/S011/20261002_S011_EX33/artifacts/evaluations"
                / record["attempt_id"]
                / "record.json"
            )
            relation = CandidateDerivation(
                CandidateKey("S011", parent.candidate_id),
                record["content_sha256"],
                CandidateKey("S011", item.candidate_id),
                StrategyRuntime().identify(item, dependencies=DEPS).content_sha256,
                CandidateDerivationKind.PARAMETERS,
                {
                    k: {"before": parent.payload["parameters"][k], "after": v}
                    for k, v in spec["parameters"].items()
                    if v != parent.payload["parameters"][k]
                },
                sha256((ROOT / "02_design.md").read_bytes()).hexdigest(),
                CandidateEvidence(
                    proof.relative_to(REPO).as_posix(), sha256(proof.read_bytes()).hexdigest()
                ),
            )
            registered = register_candidate(
                repository, CandidateRegistrationRequest(item, origin, DEPS, relation)
            )
            save(f"registrations/{item.candidate_id}.json", registered.to_dict())
            try:
                evaluate(
                    load_candidate(repository, registered.key),
                    (EvaluationCost("standard", 0.001, "FORMAL"),),
                    relation,
                )
            except Exception:
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                save("trial_failure.json", {"slot": slot, "state": "FAIL"})
                raise
            study.tell(trial, 0.0)  # Queue bookkeeping only; no objective-driven selection.
        save(
            "trial_states.json",
            {
                "optuna_version": optuna.__version__,
                "adaptive_search": False,
                "trials": [
                    {"number": t.number, "slot": t.params["slot"], "state": t.state.name}
                    for t in study.trials
                ],
            },
        )
        save("completion_results.json", results)
        family = expanded_family_statistics(REPO, historical, new_returns)
        save("expanded_family_statistics.json", family)
        save(
            "completion_summary.json",
            {
                "managed_calls": len(results),
                "new_joint_slots": 512,
                "new_pressure_accounts": 1,
                "independent_samples": 0,
                "centers_unchanged": True,
            },
        )
        return ExperimentResult(
            ExperimentOutcome.PASS,
            {"managed_calls": len(results), "joint_slots": 512},
            {"development_only": True, "stage_five_started": False},
            tuple(artifacts),
        )
