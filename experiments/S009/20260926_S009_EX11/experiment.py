from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from research_experiment import (
    ExperimentCapabilities,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


EXPERIMENT_ID = "20260926_S009_EX11"
PREDECESSOR = "20260926_S009_EX10"
PREDECESSOR_RECEIPT = "5e283dd9cddfb894103507f9b991762df7b7f63eecb75642eb4fdb339896abeb"
COMPONENT_PANEL_SHA256 = "8a8a3ee9715a3d1f7af225eec607e777d9c8a0904a6884d2a01bfac9d03302c5"


PROTOTYPES = (
    {
        "PrototypeId": "S009-P01-LIQUIDITY-PARTICIPATION",
        "MechanismScope": "DOMESTIC_LIQUIDITY",
        "Rule": "BroadLiquidity20 > 0 OR BroadLiquidity60 > 0",
        "LiquidityRule": "ANY_POSITIVE",
        "PolicyRule": "IGNORED",
        "CombinationRule": "LIQUIDITY_ONLY",
        "ExpectedBehavior": "high-participation domestic-liquidity sleeve",
    },
    {
        "PrototypeId": "S009-P02-POLICY-SAFE-HAVEN",
        "MechanismScope": "GLOBAL_POLICY_UNCERTAINTY",
        "Rule": "PolicyUncertainty20 > 0",
        "LiquidityRule": "IGNORED",
        "PolicyRule": "POSITIVE",
        "CombinationRule": "POLICY_ONLY",
        "ExpectedBehavior": "policy-news safe-haven sleeve",
    },
    {
        "PrototypeId": "S009-P03-CROSS-MECHANISM-UNION",
        "MechanismScope": "CROSS_MECHANISM",
        "Rule": "liquidity opportunity OR policy opportunity",
        "LiquidityRule": "ANY_POSITIVE",
        "PolicyRule": "POSITIVE",
        "CombinationRule": "OR",
        "ExpectedBehavior": "maximum upside participation across either mechanism",
    },
    {
        "PrototypeId": "S009-P04-CROSS-MECHANISM-CONFIRMATION",
        "MechanismScope": "CROSS_MECHANISM",
        "Rule": "liquidity opportunity AND policy opportunity",
        "LiquidityRule": "ANY_POSITIVE",
        "PolicyRule": "POSITIVE",
        "CombinationRule": "AND",
        "ExpectedBehavior": "lower-exposure joint-mechanism confirmation",
    },
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def target_for(prototype_id: str, liquidity20: float, liquidity60: float, policy20: float) -> int:
    liquidity = liquidity20 > 0 or liquidity60 > 0
    policy = policy20 > 0
    if prototype_id == "S009-P01-LIQUIDITY-PARTICIPATION":
        return int(liquidity)
    if prototype_id == "S009-P02-POLICY-SAFE-HAVEN":
        return int(policy)
    if prototype_id == "S009-P03-CROSS-MECHANISM-UNION":
        return int(liquidity or policy)
    if prototype_id == "S009-P04-CROSS-MECHANISM-CONFIRMATION":
        return int(liquidity and policy)
    raise ValueError(f"unsupported prototype: {prototype_id}")


def synthetic_precheck() -> None:
    states = (
        (-1.0, -1.0, -1.0, (0, 0, 0, 0)),
        (1.0, -1.0, -1.0, (1, 0, 1, 0)),
        (-1.0, -1.0, 1.0, (0, 1, 1, 0)),
        (-1.0, 1.0, 1.0, (1, 1, 1, 1)),
        (0.0, 0.0, 0.0, (0, 0, 0, 0)),
    )
    prototype_ids = tuple(item["PrototypeId"] for item in PROTOTYPES)
    for liquidity20, liquidity60, policy20, expected in states:
        actual = tuple(
            target_for(item, liquidity20, liquidity60, policy20) for item in prototype_ids
        )
        if actual != expected:
            raise ValueError(f"prototype truth table differs: {actual} != {expected}")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Can the three development-supported opportunity components be converted into a small, "
                "mechanistically identifiable prototype set without parameter search?"
            ),
            hypothesis=(
                "Zero-threshold liquidity and policy states can express two isolated sleeves plus OR/AND "
                "cross-mechanism combinations while retaining an auditable return-seeking interpretation."
            ),
            falsification_conditions=(
                "The EX10 component panel identity or eligibility differs",
                "Any prototype requires a learned threshold, holding-period parameter, leverage, or shorting",
                "The frozen truth table does not distinguish isolated, union, and confirmation behavior",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026091101,
            allowed_datasets=("predecessor.component_panel",),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=(
                    "A return-seeking strategy should preserve upside participation while using cash only when opportunity evidence is absent",
                    "Prototype differences must correspond to economic mechanisms rather than optimized thresholds",
                ),
                information_paths=(
                    "broad-equity ETF creations -> investable liquidity -> later gold participation",
                    "policy-news uncertainty -> global safe-haven allocation -> later gold participation",
                ),
                stage_objectives=(
                    "Freeze a low-freedom prototype catalog and one common execution contract",
                    "Preserve mechanism attribution before any return evaluation",
                ),
                observation_metrics=(
                    "prototype count, component coverage, binary-state truth table, parameter freedom",
                ),
                methodology=(
                    "Use zero as the only threshold because every component is a signed log-ratio or signed log-change",
                    "Freeze liquidity-only, policy-only, OR-union, and AND-confirmation rules",
                    "Do not read real returns, search parameters, select a winner, or create a candidate",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("pandas", pd.__version__),),
            capabilities=ExperimentCapabilities(),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX10 predecessor receipt differs")
        if predecessor.facts.get("decision") != "COMPONENT_PANEL_EXPANDED":
            raise ValueError("EX10 component-panel decision differs")
        if predecessor.facts.get("component_count") != 3:
            raise ValueError("EX10 component count differs")

        root = Path(__file__).resolve().parents[3]
        panel_path = root / "experiments/S009/20260926_S009_EX10/artifacts/component_panel.csv"
        if _sha256(panel_path) != COMPONENT_PANEL_SHA256:
            raise ValueError("EX10 component panel identity differs")
        panel = pd.read_csv(panel_path)
        expected_components = {"BroadLiquidity20", "BroadLiquidity60", "PolicyUncertainty20"}
        if set(panel["Component"]) != expected_components:
            raise ValueError("EX10 component names differ")
        if not panel["Eligible"].astype(bool).all():
            raise ValueError("EX10 component panel contains an ineligible component")
        if set(panel["Status"]) != {"DEVELOPMENT_SUPPORTED_POST_HOC"}:
            raise ValueError("EX10 component evidence status differs")

        catalog = pd.DataFrame(PROTOTYPES)
        catalog["TargetPositionWhenTrue"] = 1
        catalog["TargetPositionWhenFalse"] = 0
        catalog["LearnedParameters"] = 0
        catalog["Status"] = "FROZEN_FOR_IMPLEMENTATION_GATE"
        catalog.to_csv(
            context.workspace.path("prototype_catalog.csv"), index=False, lineterminator="\n"
        )
        contract = {
            "schema_version": 1,
            "strategy_id": "S009",
            "symbol": "518880.SH",
            "decision_time": "T_CLOSE",
            "execution_time": "T_PLUS_1_OPEN",
            "position_set": [0.0, 1.0],
            "long_only": True,
            "leverage_allowed": False,
            "shorting_allowed": False,
            "initial_cash_cny": 1000000.0,
            "primary_one_way_cost": 0.001,
            "stress_one_way_cost": 0.003,
            "lot_size": 100,
            "entry_order_type": "MARKET",
            "exit_order_type": "MARKET",
            "threshold_policy": "ECONOMIC_ZERO_ONLY",
            "minimum_holding_period": None,
            "maximum_holding_period": None,
            "hard_goals": {
                "annualized_return": ">= 1.5 * same-period BuyHold annualized return",
                "maximum_drawdown_magnitude": "< same-period BuyHold maximum drawdown magnitude",
            },
            "observation_metrics": [
                "closed_trade_frequency",
                "calmar_ratio",
                "profit_factor",
                "turnover_and_cost",
                "yearly_consistency",
                "market_exposure",
                "upside_capture_and_missed_upside",
                "downside_avoidance_and_false_defense",
                "return_concentration",
            ],
        }
        context.workspace.path("execution_contract.json").write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        synthetic_precheck()
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": "PROCEED_TO_PROTOTYPE_IMPLEMENTATION_GATE",
                "prototype_count": len(catalog),
                "component_count": len(panel),
                "mechanism_count": 2,
                "learned_parameter_count": 0,
                "binary_target_positions": True,
            },
            diagnostics={
                "reads_real_returns": False,
                "reads_sealed_validation": False,
                "search_started": False,
                "winner_selected": False,
                "candidate_created": False,
                "evidence_status": "PROTOTYPE_DEFINITION_ONLY",
            },
            artifacts=(
                context.workspace.register_artifact("prototype_catalog.csv", "S009-prototype-catalog"),
                context.workspace.register_artifact("execution_contract.json", "S009-execution-contract"),
            ),
        )
