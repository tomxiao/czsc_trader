"""Research-owned immutable decisions, inspection evidence and approval validation."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from strategy_manager import freeze_contracts as f
from strategy_manager.candidates import CandidateRegistration
from strategy_manager.models import StrategyVersion, canonical_sha256
from strategy_manager.write_lock import RegistryWriteLock
from .evidence_service import _publish_bytes


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _migration_frame_equal(left, right, identities):
    if set(left.columns) != set(right.columns) or len(left) != len(right) or not left.index.equals(right.index):
        raise ValueError("migration economic evidence shape/dates differ")
    for column in left:
        for a, b in zip(left[column], right[column], strict=True):
            if pd.isna(a) or pd.isna(b):
                if bool(pd.isna(a)) != bool(pd.isna(b)):
                    raise ValueError("migration economic evidence missing values differ")
            elif column in {"decision_id", "order_id", "fill_id", "cycle_id"}:
                if not isinstance(a, str) or not isinstance(b, str):
                    raise ValueError("migration ledger identity is invalid")
                forward, reverse = identities.setdefault(column, ({}, {}))
                if forward.setdefault(a, b) != b or reverse.setdefault(b, a) != a:
                    raise ValueError("migration ledger identity linkage differs")
            elif a != b:
                raise ValueError("migration economic evidence values differ")


def _migration_case(root, case, artifact, before, after):
    from datetime import date
    from strategy_runtime import StrategyInputBinding

    if case.get("status") != "PASS" or case.get("scope") != "REAL_AUTHENTICATED_MARKET_PUBLIC_SRT_PLAN_AT_AND_TXE":
        raise ValueError("migration requires a complete real-market equivalence case")
    start, end = date.fromisoformat(case["window"]["start"]), date.fromisoformat(case["window"]["end"])
    if start > end or case.get("initial_quantity") != 0 or case.get("initial_cash", 0) <= 0:
        raise ValueError("migration case requires a valid independent account window")
    expected_identities = []
    for definition in (before, after):
        expected_identities.append({"strategy_id": definition.strategy_family_id,
            "reference_id": definition.release_id, "release_hash": definition.release_hash,
            "runtime_sha256": definition.runtime_sha256, "symbol": definition.tradable_symbol})
    if [case["identity"][key] for key in ("old_identity", "new_identity")] != expected_identities:
        raise ValueError("migration case original/candidate runtime identity differs")
    bindings = [StrategyInputBinding.from_mapping(_read(artifact(f"{name}_binding.json")))
                for name in ("old", "new")]
    if bindings[0].prepared != bindings[1].prepared:
        raise ValueError("migration case must use the same admitted preparation")
    plans = [binding.plan.to_dict() for binding in bindings]
    for plan, identity in zip(plans, expected_identities, strict=True):
        if plan.pop("strategy") != identity or plan["tradable_window"] != case["window"]:
            raise ValueError("migration case input plan belongs to another runtime/window")
        for request in plan["requests"].values():
            if request["parameter_type"] == "EvidenceParameters":
                request["parameters"]["repository_root"] = "<physical-evidence-root>"
    if plans[0] != plans[1]:
        raise ValueError("migration case input selections or date mappings differ")
    if set(case["modes"]) != {"WINDOW", "CONTINUOUS"}:
        raise ValueError("migration evidence must cover window and continuous modes")
    for mode, result in case["modes"].items():
        if result.get("status") != "PASS" or result["signals"]["comparison"] != "EXACT_VALUES_ZERO_TOLERANCE":
            raise ValueError("migration case signal comparison is incomplete")
        signals = [pd.read_csv(artifact(f"{name}_{mode}_signals_full.csv"), index_col=0,
                    parse_dates=[0], float_precision="round_trip") for name in ("old", "new")]
        if any(frame.index.has_duplicates or not frame.index.is_monotonic_increasing for frame in signals):
            raise ValueError("migration signal evidence has invalid dates")
        if not len(signals[1]) or result["signals"]["rows"] != len(signals[1]):
            raise ValueError("migration signal evidence is empty or miscounted")
        _migration_frame_equal(signals[0].reindex(signals[1].index), signals[1], {})
        checks = result["ledgers"]["checks"]
        names = ("decisions", "orders", "fills", "account_daily", "trades")
        if len(checks) != len(names) or {item["name"] for item in checks} != set(names):
            raise ValueError("migration requires all five economic ledgers")
        identities = {}
        for name in names:
            frames = [pd.read_csv(artifact(f"{side}_{mode}_{name}.csv"), float_precision="round_trip")
                      for side in ("old", "new")]
            check = next(item for item in checks if item["name"] == name)
            if check["comparison"] != "EXACT_VALUES_ZERO_TOLERANCE" or check["rows"] != len(frames[1]):
                raise ValueError("migration ledger comparison is incomplete or miscounted")
            _migration_frame_equal(*frames, identities)
            if name == "fills" and (not len(frames[1]) or result["actual_fills"] != {
                    "old": len(frames[0]), "new": len(frames[1])}):
                raise ValueError("migration evidence must contain actual matched fills")
        probes = _read(artifact(f"nonzero_plan_probes_{mode}.json"))
        if probes.get("coverage_sufficient") is not True or probes.get("failures") or not probes.get("cases"):
            raise ValueError("migration nonzero-account coverage is incomplete")
        quantities = set()
        for probe in probes["cases"]:
            quantities.add(probe["quantity"])
            if probe["status"] == "EXACT_PUBLIC_PLAN":
                values = []
                for side, identity in zip(("old", "new"), expected_identities, strict=True):
                    value = dict(probe[side])
                    if value.pop("strategy") != identity:
                        raise ValueError("migration nonzero plan runtime differs")
                    for field in ("signal_identity", "plan_identity"):
                        value.pop(field)
                    values.append(value)
                if values[0] != values[1]:
                    raise ValueError("migration nonzero plan economic facts differ")
            elif (probe["status"] != "EXPECTED_INVALID_CORE_QUANTITY_BOUNDARY"
                  or probe["old"] != probe["new"] or probe["old"].get("type") != "RuntimeContractError"):
                raise ValueError("migration nonzero plan boundary differs")
        if not {200, 600} <= quantities:
            raise ValueError("migration requires both nonzero account quantities")


def validate_migration_selection(context, subject):
    """Recheck a frozen origin and the actual immutable case artifact closure."""
    from strategy_manager import StrategyRegistry
    from strategy_runtime import StrategyRuntime, RuntimeBinding, ImplementationDependency
    from ..research_tools.evidence import EvidenceRef
    from .candidate_service import load_candidate
    from .runtime_acceptance import prospective_release
    from .runtime_migration import validate_frozen_runtime_migration, _migration_original

    if type(subject) is not f.FrozenMigrationSelectionSubject:
        raise TypeError("migration selection must be typed")
    candidate = load_candidate(context, subject.candidate)
    after = validate_frozen_runtime_migration(context, subject.original, candidate)
    registration = StrategyRegistry(context.research_registry_root).get_candidate(
        subject.candidate, evidence_root=context.research_root / subject.candidate.strategy_id)
    identity = StrategyRuntime().identify(candidate, dependencies=tuple(
        ImplementationDependency(*item) for item in registration.dependencies))
    if identity.content_sha256 != subject.content_sha256 or registration.content_sha256 != subject.content_sha256:
        raise ValueError("migration selection candidate content identity differs")
    reference = f"{subject.original.strategy_id}-{subject.original.version}"
    original, _, binding, source = _migration_original(context, subject.original)
    before = StrategyRuntime().describe(prospective_release(original), source_root=source,
                                       runtime_binding=RuntimeBinding.from_dict(binding))
    documents = [(ref, _read(ref.resolve(context.root))) for ref in subject.equivalence_evidence]
    manifests = [value for _, value in documents if isinstance(value, dict)
                 and "artifacts" in value and "selected_migrations" in value]
    if len(manifests) != 1:
        raise ValueError("migration selection requires one published artifact manifest")
    manifest = manifests[0]
    selected = manifest["selected_migrations"][reference]
    if (selected["candidate_id"] != candidate.candidate_id
            or selected["candidate_identity"] != {
                "content_sha256": identity.content_sha256, "source_sha256": identity.source_sha256,
                "dependency_sha256": identity.dependency_sha256, "schema_version": identity.schema_version}):
        raise ValueError("migration artifact manifest candidate identity differs")
    cases = [(ref, value) for ref, value in documents if isinstance(value, dict)
             and value.get("reference") == reference and "modes" in value]
    if not cases:
        raise ValueError("migration selection requires a published real equivalence case")
    for ref, case in cases:
        published = [path for path, raw in manifest["artifacts"].items()
                     if raw["sha256"] == ref.sha256 and EvidenceRef.from_dict(raw).resolve(context.root) == ref.resolve(context.root)]
        if len(published) != 1 or Path(published[0]).name != "result.json":
            raise ValueError("migration case is absent from its published artifact manifest")
        prefix = Path(published[0]).parent
        entries = {item["path"]: item["sha256"] for item in case["artifacts"]}
        if len(entries) != len(case["artifacts"]):
            raise ValueError("migration case artifact closure has duplicate paths")

        def artifact(name):
            path = (prefix / name).as_posix()
            expected = entries.get(path)
            raw = manifest["artifacts"].get(path)
            if expected is None or raw is None or raw["sha256"] != expected:
                raise ValueError("migration evidence artifact closure is incomplete")
            return EvidenceRef.from_dict(raw).resolve(context.root)

        for path in entries:
            if Path(path).parent != prefix:
                raise ValueError("migration evidence artifact escapes its case")
            artifact(Path(path).name)
        _migration_case(context.root, case, artifact, before, after)
    return original


def validate_migration_target(context, subject, version, parent, cutoff, forward, *, available=False):
    from strategy_manager import StrategyRegistry

    original = validate_migration_selection(context, subject)
    inplace = version == original.version
    expected_parent = original.parent_version if inplace else original.version
    if (parent, cutoff, forward) != (expected_parent, original.selection_data_cutoff, original.forward_start):
        raise ValueError("migration must preserve original parent, selection cutoff and forward start")
    if available:
        family = context.strategy_root / subject.candidate.strategy_id
        if not inplace and ((family / "versions" / f"{version}.json").exists() or (family / "releases" / version).exists()):
            raise ValueError("migration target version is already occupied")
        journal = context.research_root / subject.candidate.strategy_id / "freeze_requests"
        for path in journal.glob("*/request.json"):
            prior = _read(path)
            if prior["version"]["version"] == version:
                terminal = path.parent / "committed.json"
                if inplace and terminal.exists():
                    committed = f.FreezeReceipt.from_dict(_read(terminal))
                    if (committed.status is f.FreezeStatus.COMMITTED
                            and committed.request_id == f.FreezeRequestId.from_dict(prior["request_id"])
                            and committed.request_sha256 == prior["request_sha256"]):
                        continue
                status = StrategyRegistry(context.strategy_root).get_freeze_result(
                    f.FreezeRequestId.from_dict(prior["request_id"]), journal_root=journal).status
                if status in {f.FreezeStatus.UNKNOWN, f.FreezeStatus.IN_PROGRESS}:
                    raise ValueError("migration target version is reserved by an unresolved request")


def validate_migration_files(context, subject, files, *, registered=()):
    """Additional package files cannot add code outside the reviewed conversion."""
    from .runtime_migration import _migration_original

    _, _, binding, source = _migration_original(context, subject.original)
    expected = {item.path: item.source.sha256 for item in registered}
    present = set()
    for item in files:
        present.add(item.path)
        data = item.source.resolve(context.root).read_bytes()
        if item.path in expected:
            if sha256(data).hexdigest() != expected[item.path]:
                raise ValueError("migration plan source differs from registered conversion")
        elif item.path not in binding["install_files"] or data != (source / item.path).read_bytes():
            raise ValueError("migration package adds or changes unreviewed files")
    if expected and not set(expected) <= present:
        raise ValueError("migration plan omits registered source files")


def read_decision(root, ref):
    if type(ref) is not f.DecisionReference:
        raise TypeError("decision requires DecisionReference")
    decision = f.ResearchDecision.from_dict(_read(ref.evidence.resolve(root)))
    if ref.decision_id != decision.decision_id:
        raise ValueError("decision identity differs")
    if (
        type(decision.confirmation_source) is not f.ResearchEvidenceRef
        or ref.evidence.owner != f.ResearchEvidenceOwner(decision.strategy_id)
        or decision.confirmation_source.owner != ref.evidence.owner
    ):
        raise ValueError("decision evidence owner differs")
    decision.confirmation_source.resolve(root)
    return decision


def record_decision(context, decision):
    owner = f.ResearchEvidenceOwner(decision.strategy_id)
    if type(decision.confirmation_source) is not f.ResearchEvidenceRef:
        raise TypeError("persisted confirmation requires ResearchEvidenceRef")
    decision.confirmation_source.resolve(context.root)
    ref = f.DecisionReference(
        decision.decision_id,
        f.ResearchEvidenceRef(
            owner,
            f"decisions/{decision.decision_id}.json",
            sha256(_bytes(decision.to_dict())).hexdigest(),
        ),
    )
    path = context.root / ref.evidence.repository_path
    with RegistryWriteLock(context.root / ".tmp/research-locks" / decision.strategy_id).hold():
        if path.exists():
            ref.evidence.resolve(context.root)
        else:
            _publish_bytes(context.root, path, _bytes(decision.to_dict()))
    return ref


def inspection_evidence_references(root, report):
    """Closed technical evidence graph; registration history is metadata only."""
    refs = [report.origin.registration, report.request, report.protocol, report.measurements]
    if report.environment is not None:
        refs.append(report.environment)
    if report.plan is not None:
        refs.extend((report.plan.payload, report.plan.runtime_binding))
        refs.extend(x.source for x in report.plan.source_files)
    if report.release is not None:
        refs.extend((report.release.version_record, report.release.manifest))
        refs.extend(x.source for x in report.release.files)
    for goal in (report.behavior_equivalence, report.pte_runtime):
        refs.extend(goal.evidence)
        for case in goal.cases:
            refs.extend(case.evidence)
    unique = tuple(dict.fromkeys(refs))
    for ref in unique:
        if type(ref) is not f.ResearchEvidenceRef or ref.owner != report.owner:
            raise ValueError("inspection evidence owner differs")
        ref.resolve(root)
    return unique


def validate_inspection(root, reference):
    report = f.CandidateInspectionReport.from_dict(_read(reference.resolve(root)))
    if report.reference != reference:
        raise ValueError("inspection reference differs from report owner")
    inspection_evidence_references(root, report)
    normalized = _read(report.request.resolve(root))
    protocol = _read(report.protocol.resolve(root))
    if (normalized.get("schema_version") != 2 or normalized.get("protocol_sha256") != report.protocol.sha256
            or normalized.get("candidate") != report.origin.candidate.to_dict()
            or normalized.get("selection") != report.selection.to_dict()
            or normalized.get("experiment") != {"type": "ExperimentRef", "strategy_id": report.owner.strategy_id, "experiment_id": report.owner.experiment_id}
            or normalized.get("data_kind") not in {"HISTORICAL", "SYNTHETIC"}
            or protocol.get("method_version") != "candidate-inspection-v2" or protocol.get("comparison") != "ECONOMIC_V1"):
        raise ValueError("inspection request/protocol identity differs")
    origin, plan = report.origin, report.plan
    registration = CandidateRegistration.from_dict(_read(origin.registration.resolve(root)))
    if (registration.key != origin.candidate or registration.content_sha256 != origin.content_sha256
            or registration.record_sha256 != origin.registration_sha256):
        raise ValueError("inspection registration origin differs")
    selection = read_decision(root, report.selection)
    if (selection.action is not f.DecisionAction.APPROVE
            or type(selection.subject) not in (f.CandidateSelectionSubject, f.FrozenMigrationSelectionSubject)
            or selection.subject.candidate != origin.candidate
            or selection.subject.content_sha256 != origin.content_sha256):
        raise ValueError("inspection selection differs")
    if isinstance(selection.subject, f.CandidateSelectionSubject) and selection.subject.registration_sha256 != registration.record_sha256:
        raise ValueError("inspection selection registration differs")
    if plan is None:
        return report
    if normalized["target"] != {"version": plan.version, "parent_version": plan.parent_version,
            "change_summary": plan.change_summary, "selection_data_cutoff": plan.selection_data_cutoff.isoformat(),
            "forward_start": plan.forward_start.isoformat()}:
        raise ValueError("inspection target differs from plan")
    if (registration.payload.sha256 != plan.payload.sha256 or registration.origin.experiment_id != plan.source_experiment):
        raise ValueError("inspection plan differs from registered candidate")
    planned = {x.path: x.source.sha256 for x in plan.source_files}
    prefix = registration.source_root + "/"
    if any(planned.get(x.path.removeprefix(prefix)) != x.sha256 for x in registration.source_files):
        raise ValueError("inspection plan source differs from registration")
    if report.release is not None:
        release = report.release
        version = StrategyVersion.from_dict(_read(release.version_record.resolve(root)))
        if version != build_version_from_plan(root, plan, selection.subject) or release.release_sha256 != version.release_hash:
            raise ValueError("inspected version differs from plan")
        manifest = _read(release.manifest.resolve(root))
        identity = dict(manifest)
        digest = identity.pop("package_hash")
        if digest != canonical_sha256(identity) or digest != release.package_sha256:
            raise ValueError("inspected package hash differs")
        if (manifest["strategy_version_hash"] != version.release_hash
                or manifest["strategy_version_id"] != version.release_id
                or manifest["candidate_package_hash"] != plan.sha256
                or manifest["files"] != {x.path: x.source.sha256 for x in release.files}):
            raise ValueError("inspected manifest differs from plan or file closure")
        contents = {x.path: x.source for x in release.files}
        expected_paths = {"src/strategy_runtime/" + x.path for x in plan.source_files} | {"runtime_binding.json"}
        if set(contents) != expected_paths or any(contents["src/strategy_runtime/" + x.path].sha256 != x.source.sha256 for x in plan.source_files):
            raise ValueError("inspected package source closure differs from plan")
        binding = _read(contents["runtime_binding.json"].resolve(root))
        if binding != {**_read(plan.runtime_binding.resolve(root)), "release_id": version.release_id, "release_hash": version.release_hash}:
            raise ValueError("inspected runtime binding differs from plan")
    if report.status is f.InspectionStatus.PASS:
        _validate_pass_facts(root, report, normalized, protocol)
    return report


def _validate_pass_facts(root, report, normalized, protocol):
    """Recheck saved deterministic results, without executing research or strategy code."""
    from strategy_evaluator import ReplayEvidence, compare_ledgers, LedgerComparisonRequest, LedgerComparisonMode, LedgerComparisonStatus
    from .inspection_replay import technical_ledger_differences
    from .inspection_inputs import portable_value
    tolerance = protocol["float_tolerance"]
    replays = normalized["replays"]
    cases = report.behavior_equivalence.cases
    if not replays or len(cases) != len(replays):
        raise ValueError("passing inspection replay coverage differs")
    for index, (case, replay) in enumerate(zip(cases, replays, strict=True)):
        if case.case_id != "replay-" + str(index):
            raise ValueError("passing replay case identity differs")
        facts = _read(case.evidence[-1].resolve(root))
        inputs = _read(case.evidence[-2].resolve(root))
        if (inputs["data_kind"] != normalized["data_kind"] or inputs["data_kind_source"] != "CALLER_DECLARATION"
                or inputs["strategy_prepared"] != replay["input_binding"]["prepared"]
                or inputs["execution_prepared"] != replay["execution"]["prepared"]):
            raise ValueError("passing replay input origins differ")
        if facts.get("passed") is not True or facts.get("signal_error") is not None or facts.get("observations_equal") is not True:
            raise ValueError("passing replay lacks equivalent facts")
        if facts["candidate_observations"] != facts["release_observations"]:
            raise ValueError("passing replay observations differ")
        if facts["candidate_signals"] != facts["release_signals"]:
            raise ValueError("passing replay signals differ")
        left_binding, right_binding = portable_value(facts["candidate_binding"]), portable_value(facts["release_binding"])
        if left_binding != replay["input_binding"]:
            raise ValueError("passing replay candidate input differs from request")
        left_plan, right_plan = dict(left_binding["plan"]), dict(right_binding["plan"])
        left_plan.pop("strategy")
        release_identity = right_plan.pop("strategy")
        if (left_plan != right_plan or left_binding["prepared"] != right_binding["prepared"]
                or release_identity["release_hash"] != report.release.release_sha256):
            raise ValueError("passing replay release input differs")
        left, right = ReplayEvidence.from_dict(facts["candidate"]), ReplayEvidence.from_dict(facts["release"])
        if (left.initial_cash != replay["initial_cash"] or left.data_hash != replay["execution"]["fingerprint"]
                or right.strategy_hash != report.release.release_sha256):
            raise ValueError("passing replay execution identity differs")
        compared = compare_ledgers(LedgerComparisonRequest(left, right, LedgerComparisonMode.ECONOMIC, tolerance))
        if (compared.status is not LedgerComparisonStatus.EQUIVALENT or compared.to_dict() != facts["comparison"]
                or facts.get("differences") != [] or technical_ledger_differences(facts["candidate"], facts["release"], tolerance)):
            raise ValueError("passing replay comparison differs")
        expected_baseline = "NOT_REQUESTED" if replay["baseline"] is None else "PASS"
        if facts["baseline"]["status"] != expected_baseline:
            raise ValueError("passing replay baseline result differs")
        if replay["baseline"] is not None:
            if len(case.evidence) < 3:
                raise ValueError("requested baseline evidence missing")
            baseline = _read(case.evidence[0].resolve(root))
            ids = replay["baseline"]["evaluation_ids"]
            matched = [x for x in baseline["runs"] if (x["window_id"], x["scenario_id"]) ==
                (replay["coordinate"]["window_id"], replay["coordinate"]["scenario_id"])
                and (not ids or canonical_sha256(x["identity"]) in ids)]
            if len(matched) != 1:
                raise ValueError("saved baseline coordinate differs")
            again = compare_ledgers(LedgerComparisonRequest(ReplayEvidence.from_dict(matched[0]["replay_evidence"]), left,
                                                            LedgerComparisonMode.ECONOMIC, tolerance))
            if (again.status is not LedgerComparisonStatus.EQUIVALENT or again.to_dict() != facts["baseline"]["comparison"]
                    or facts["baseline"].get("differences") != []
                    or technical_ledger_differences(matched[0]["replay_evidence"], facts["candidate"], tolerance)):
                raise ValueError("saved baseline comparison differs")
    coverage_cases = [x for x in report.pte_runtime.cases if x.case_id == "pte-coverage"]
    if len(coverage_cases) != 1:
        raise ValueError("passing PTE coverage evidence missing")
    coverage = _read(coverage_cases[0].evidence[0].resolve(root))
    environment = _read(report.environment.resolve(root))
    if (coverage["status"] != "PASS" or coverage["environment"] != environment
            or coverage["data_kind"] != normalized["data_kind"] or coverage["channel_kind"] != "SYNTHETIC"):
        raise ValueError("passing PTE environment or status differs")
    for key, value in protocol["pte"]["environment"].items():
        if environment[key] != value:
            raise ValueError("passing inspection environment differs from protocol")
    declared = protocol["pte"]["coverage"]
    observed = coverage["coverage"]
    if len(declared) != len(observed) or any(
            {k: row[k] for k in ("capability", "requirement", "scenario_ids", "reason")} != requirement or row["covered"] is not True
            for row, requirement in zip(observed, declared, strict=True)):
        raise ValueError("passing PTE capability coverage differs")
    expected_cases = {x["scenario_id"] for x in protocol["pte"]["scenarios"]} | {x["case_id"] for x in protocol["pte"]["failures"]} | {"pte-coverage"}
    if {x.case_id for x in report.pte_runtime.cases} != expected_cases:
        raise ValueError("passing PTE scenario coverage differs")
    from .inspection_evidence import validate_pte_facts
    validate_pte_facts(root, report, normalized, protocol)


def validate_approval(root, request):
    report = validate_inspection(root, request.inspection)
    approval = read_decision(root, request.approval)
    plan = report.plan
    if plan is None:
        raise ValueError("freeze requires a complete passing inspection with a plan")
    expected = f.FreezeSubject(
        plan.origin.candidate,
        plan.origin.content_sha256,
        request.inspection,
        plan.sha256,
        plan.version,
    )
    if (
        report.status is not f.InspectionStatus.PASS
        or approval.action is not f.DecisionAction.APPROVE
        or approval.subject != expected
        or request.request_id.strategy_id != plan.origin.candidate.strategy_id
    ):
        raise ValueError("freeze requires matching approval and complete passing inspection")
    return report


def build_version_from_plan(root, plan, selection_subject=None):
    if (isinstance(selection_subject, f.FrozenMigrationSelectionSubject)
            and selection_subject.original.version == plan.version):
        from .context import RepositoryContext
        from .runtime_migration import _migration_original
        original, _, _, _ = _migration_original(RepositoryContext.discover(Path(root)), selection_subject.original)
        version = replace(original, strategy_payload=_read(plan.payload.resolve(root)), release_hash="0" * 64)
        return replace(version, release_hash=canonical_sha256(version.release_payload()))
    candidate = plan.origin.candidate
    version = StrategyVersion(
        5,
        candidate.strategy_id,
        plan.version,
        f"{candidate.strategy_id}-{plan.version}",
        plan.parent_version,
        plan.change_summary,
        plan.source_experiment,
        candidate.candidate_id,
        plan.selection_data_cutoff.isoformat(),
        plan.forward_start.isoformat(),
        _read(plan.payload.resolve(root)),
        "0" * 64,
    )
    return StrategyVersion.from_dict(
        replace(version, release_hash=canonical_sha256(version.release_payload())).to_dict()
    )
