from __future__ import annotations

from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.experiment_archive import validate_experiment_archive
import numpy as np
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


EX70 = "20260924_S008_EX70"
EX71 = "20260924_S008_EX71"
EX70_RECEIPT = "f56689b29a6602e4ac6df171a40d6b91bbd6bb46a5c343e1952aa74d97f434d9"
EX71_RECEIPT = "57f2d74df5429e0c7dd0ad689d9b4d34c485932b1ab080d1d272702b5a49ae6c"
EX16_MANIFEST_SHA256 = "416340591eb7d24c169496293a27d4445785ac26e88142229139ab320ec5e0ae"
EX18_MANIFEST_SHA256 = "eab14f3ad0f694d996717d998577dfd5abdd4939736ccf2b43a7fb55a70f4933"
NEW_FEATURES = ("AfternoonReturn", "CloseLocation", "OvernightGap")
REDUNDANCY_THRESHOLD = 0.80


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _verified_artifact(context, experiment_id: str, name: str) -> Path:
    predecessor = context.predecessors[experiment_id]
    artifact = next((item for item in predecessor.artifacts if item.path == name), None)
    if artifact is None:
        raise ValueError(f"{experiment_id} is missing {name}")
    path = _root() / "experiments" / "S008" / experiment_id / "artifacts" / name
    if sha256(path.read_bytes()).hexdigest() != artifact.sha256:
        raise ValueError(f"{experiment_id} artifact differs from its receipt: {name}")
    return path


def _verified_legacy_archive(experiment_id: str, expected_manifest: str) -> Path:
    root = _root() / "experiments" / "S008" / experiment_id
    manifest_path = root / "experiment_manifest.json"
    if sha256(manifest_path.read_bytes()).hexdigest() != expected_manifest:
        raise ValueError(f"{experiment_id} manifest identity differs")
    validate_experiment_archive(root)
    return root


def _clusters(correlation: pd.DataFrame) -> list[list[str]]:
    names = sorted(correlation.columns)
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for ordinal, left in enumerate(names):
        for right in names[ordinal + 1 :]:
            value = correlation.loc[left, right]
            if pd.notna(value) and abs(float(value)) >= REDUNDANCY_THRESHOLD:
                union(left, right)
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(find(name), []).append(name)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX72",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Are the three EX71 intraday rebound paths independent of existing S008 components and ready for prototype design?",
            hypothesis="At least one path is numerically distinct, but all three share an entry-timing rather than an opportunity-source role.",
            falsification_conditions=(
                "The frozen EX70, EX71, EX16 or EX18 evidence identity differs",
                "The new paths are redundant with existing components at absolute Spearman 0.80",
                "Independent paths lack the preregistered strength required to review a prototype",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097201,
            allowed_datasets=("etf.ohlcv.managed", "strategy.feature_evidence"),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Weak same-day ETF trading may encode a rebound entry moment but cannot establish an independent gold opportunity",
                    "Repeated measures of the same price state should not count as additional information",
                ),
                information_paths=(
                    "EX70 intraday descriptors -> EX71 frozen direction -> EX18 component redundancy",
                    "numerical independence + evidence strength + financial role -> prototype review decision",
                ),
                stage_objectives=(
                    "Review numerical redundancy and business responsibility without reading new returns",
                ),
                observation_metrics=(
                    "discovery and confirmation absolute Spearman correlation",
                    "pairwise sample count, redundancy clusters, independent representatives",
                ),
                methodology=(
                    "Compare all three fixed EX71 paths with all 13 EX18 representatives at threshold 0.80",
                    "Assign ENTRY_TIMING rebound role before viewing new correlation results",
                    "Require at least NOMINAL_SUPPORT before recommending prototype review",
                ),
                predecessor_experiment_ids=(EX70, EX71),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context) -> ExperimentResult:
        if context.predecessors[EX70].receipt_sha256 != EX70_RECEIPT:
            raise ValueError("EX70 receipt identity differs")
        if context.predecessors[EX71].receipt_sha256 != EX71_RECEIPT:
            raise ValueError("EX71 receipt identity differs")
        if context.predecessors[EX71].facts.get("decision") != "PROCEED_INTRADAY_ROLE_REVIEW":
            raise ValueError("EX71 did not authorize the intraday role review")
        ex16 = _verified_legacy_archive("20260923_S008_EX16", EX16_MANIFEST_SHA256)
        ex18 = _verified_legacy_archive("20260923_S008_EX18", EX18_MANIFEST_SHA256)
        intraday_path = _verified_artifact(context, EX70, "intraday_causal_panel.csv.gz")
        ledger_path = _verified_artifact(context, EX71, "information_path_ledger.csv.gz")

        prior_components = pd.read_csv(ex18 / "artifacts" / "component_panel.csv")
        if len(prior_components) != 13 or prior_components["feature"].nunique() != 13:
            raise ValueError("EX18 component panel does not contain 13 unique paths")
        prior_names = prior_components["feature"].tolist()
        old_orientations = prior_components.set_index("feature")["orientation"].map(
            {"POSITIVE": 1.0, "NEGATIVE": -1.0}
        )
        if old_orientations.isna().any():
            raise ValueError("EX18 component orientation is incomplete")
        ledger = pd.read_csv(ledger_path)
        selected = ledger.loc[ledger["horizon"].eq(20) & ledger["feature"].isin(NEW_FEATURES)]
        if (
            len(selected) != 3
            or set(selected["feature"]) != set(NEW_FEATURES)
            or not selected["orientation"].eq("NEGATIVE").all()
            or not selected["evidence_label"].eq("DIRECTIONALLY_STABLE").all()
        ):
            raise ValueError("EX71 selected path contract differs")
        selected = selected.set_index("feature")

        old_panel = pd.read_csv(
            ex16 / "artifacts" / "causal_feature_panel.csv.gz", parse_dates=["Date"]
        ).set_index("Date")
        new_panel = pd.read_csv(intraday_path, parse_dates=["Date"]).set_index("Date")
        if (
            not old_panel.index.equals(new_panel.index)
            or len(new_panel) != 2781
            or new_panel.index.min() != pd.Timestamp("2013-07-29")
            or new_panel.index.max() != pd.Timestamp("2024-12-31")
            or not new_panel.index.is_unique
        ):
            raise ValueError("frozen feature panels have different development calendars")
        combined = pd.concat(
            [
                old_panel.loc[:, prior_names].mul(old_orientations, axis=1),
                -new_panel.loc[:, list(NEW_FEATURES)],
            ],
            axis=1,
        )
        discovery = combined.loc[combined.index <= pd.Timestamp("2018-12-31")]
        confirmation = combined.loc[combined.index >= pd.Timestamp("2019-01-01")]
        discovery_corr = discovery.corr(method="spearman", min_periods=1000)
        confirmation_corr = confirmation.corr(method="spearman", min_periods=1000)
        comparisons = []
        for new_name in NEW_FEATURES:
            for other_name in sorted(set(prior_names) | (set(NEW_FEATURES) - {new_name})):
                sample_count = int(confirmation[[new_name, other_name]].dropna().shape[0])
                if sample_count < 1000:
                    raise ValueError(f"insufficient confirmation pairs: {new_name}, {other_name}")
                comparisons.append(
                    {
                        "new_feature": new_name,
                        "compared_feature": other_name,
                        "comparison_type": "EXISTING" if other_name in prior_names else "NEW",
                        "discovery_rho": float(discovery_corr.loc[new_name, other_name]),
                        "confirmation_rho": float(confirmation_corr.loc[new_name, other_name]),
                        "confirmation_pairs": sample_count,
                        "numerically_redundant": bool(
                            abs(float(confirmation_corr.loc[new_name, other_name]))
                            >= REDUNDANCY_THRESHOLD
                        ),
                    }
                )
        comparison_frame = pd.DataFrame(comparisons).sort_values(
            ["new_feature", "comparison_type", "compared_feature"]
        )
        groups = _clusters(confirmation_corr)
        cluster_by_feature = {
            feature: index for index, members in enumerate(groups, start=1) for feature in members
        }
        group_representatives: dict[int, str] = {}
        for group_index, members in enumerate(groups, start=1):
            new_members = [name for name in members if name in NEW_FEATURES]
            old_members = [name for name in members if name in prior_names]
            if new_members and not old_members:
                group_representatives[group_index] = sorted(
                    new_members,
                    key=lambda name: (
                        -float(selected.loc[name, "bootstrap_positive_probability"]),
                        -float(selected.loc[name, "confirmation_partial_ic"]),
                        name,
                    ),
                )[0]
        review_rows = []
        for name in NEW_FEATURES:
            matches = comparison_frame.loc[comparison_frame["new_feature"].eq(name)]
            against_existing = matches.loc[matches["comparison_type"].eq("EXISTING")]
            most_related = against_existing.iloc[
                against_existing["confirmation_rho"].abs().to_numpy().argmax()
            ]
            cluster_index = cluster_by_feature[name]
            representative = group_representatives.get(cluster_index)
            status = (
                "REDUNDANT_WITH_EXISTING"
                if representative is None
                else "INDEPENDENT_REPRESENTATIVE"
                if representative == name
                else "REDUNDANT_WITH_NEW_REPRESENTATIVE"
            )
            review_rows.append(
                {
                    "feature": name,
                    "financial_role": "ENTRY_TIMING",
                    "mechanism": "ETF same-day weakness followed by potential rebound",
                    "existing_role_overlap": "EX18 has three price-state ENTRY_TIMING components",
                    "evidence_label": selected.loc[name, "evidence_label"],
                    "cluster_id": f"C{cluster_index:03d}",
                    "cluster_members": " | ".join(groups[cluster_index - 1]),
                    "representative": representative or "",
                    "status": status,
                    "most_related_existing": most_related["compared_feature"],
                    "maximum_existing_abs_rho": abs(float(most_related["confirmation_rho"])),
                    "most_related_existing_discovery_rho": float(most_related["discovery_rho"]),
                    "confirmation_partial_ic_from_ex71": float(
                        selected.loc[name, "confirmation_partial_ic"]
                    ),
                    "bootstrap_probability_from_ex71": float(
                        selected.loc[name, "bootstrap_positive_probability"]
                    ),
                }
            )
        review = pd.DataFrame(review_rows)
        independent = review.loc[review["status"].eq("INDEPENDENT_REPRESENTATIVE")]
        if independent.empty:
            decision = "STOP_INTRADAY_REDUNDANT"
        elif independent["evidence_label"].isin({"NOMINAL_SUPPORT", "FDR_SUPPORTED"}).any():
            decision = "REVIEW_ENTRY_OVERLAY_PROTOTYPE"
        else:
            decision = "HOLD_INTRADAY_DISCOVERY_ONLY"

        comparison_path = context.workspace.path("correlation_comparisons.csv.gz")
        comparison_frame.to_csv(
            comparison_path,
            index=False,
            compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
            lineterminator="\n",
        )
        review_path = context.workspace.path("intraday_role_review.csv")
        review.to_csv(review_path, index=False, lineterminator="\n")
        audit = {
            "schema_version": 1,
            "decision": decision,
            "threshold": REDUNDANCY_THRESHOLD,
            "comparison_count": len(comparison_frame),
            "existing_components": len(prior_names),
            "new_paths": len(NEW_FEATURES),
            "clusters": [
                {
                    "id": f"C{index:03d}",
                    "members": members,
                    "new_representative": group_representatives.get(index),
                }
                for index, members in enumerate(groups, start=1)
            ],
            "independent_new_representatives": independent["feature"].tolist(),
            "new_return_labels_read": False,
            "sealed_validation_read": False,
            "prototype_selected": False,
            "parameter_search_started": False,
        }
        audit_path = context.workspace.path("redundancy_audit.json.gz")
        audit_path.write_bytes(
            gzip.compress(
                (
                    json.dumps(audit, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
                ).encode("utf-8"),
                mtime=0,
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE
            if decision == "HOLD_INTRADAY_DISCOVERY_ONLY"
            else ExperimentOutcome.PASS,
            facts={
                "decision": decision,
                "comparison_count": len(comparison_frame),
                "independent_new_representatives": independent["feature"].tolist(),
                "redundant_new_count": int(len(review) - len(independent)),
                "maximum_existing_absolute_correlation": {
                    row["feature"]: row["maximum_existing_abs_rho"] for row in review_rows
                },
            },
            diagnostics={
                "new_return_labels_read": False,
                "sealed_validation_read": False,
                "prototype_selected": False,
                "parameter_search_started": False,
                "candidate_created": False,
            },
            artifacts=(
                context.workspace.register_artifact(
                    "correlation_comparisons.csv.gz", "complete-redundancy-comparisons"
                ),
                context.workspace.register_artifact(
                    "intraday_role_review.csv", "intraday-financial-role-review"
                ),
                context.workspace.register_artifact(
                    "redundancy_audit.json.gz", "redundancy-and-role-audit"
                ),
            ),
        )
