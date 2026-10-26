"""Direct archived-release versus installed-release replay on authenticated inputs."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import argparse
import cloudpickle
import pandas as pd

import upgrade_batch as v
from czsc_trader.application import RepositoryContext, create_research_context, validate_release_package
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources
from dataflows import (
    Dataflows, DataSpace, EvidenceParameters, ProviderBinding, ProviderConfig,
    PreparePolicy, canonical_frame_sha256,
)
from strategy_manager import StrategyRegistry
from strategy_runtime import (
    RuntimeBinding, SignalHistoryMode, StrategyInit, StrategyInputBinding,
    StrategyRelease, StrategyRuntime,
)


def normalize_request(request, original):
    if isinstance(request.parameters, EvidenceParameters) and isinstance(original.parameters, EvidenceParameters):
        return replace(request, parameters=replace(request.parameters, repository_root=original.parameters.repository_root))
    return request


def main(reference):
    item = v.ITEMS[reference]
    family, version = reference.split("-")
    home = v.ROOT / item["home"]
    out = home / "others" / reference / "published_equivalence"
    out.mkdir(parents=True, exist_ok=True)
    if (out / "result.json").exists():
        raise FileExistsError("Published equivalence already exists; review before starting another run")
    repo = RepositoryContext.discover(v.ROOT)
    old_repo = replace(repo, strategy_root=repo.strategy_root / "revisions" / reference /
                       item["original"]["release_hash"] / "strategies")
    old_manifest, old_binding, old_source = validate_release_package(old_repo, reference)
    new_manifest, new_binding, new_source = validate_release_package(repo, reference)
    assert old_manifest["strategy_version_hash"] == item["original"]["release_hash"]
    assert old_manifest["strategy_version_hash"] != new_manifest["strategy_version_hash"]
    old = StrategyRelease.from_mapping(item["original"])
    current = StrategyRegistry(repo.strategy_root).get_version(family, version)
    new = StrategyRelease.from_mapping(current.to_dict())
    old_payload = dict(old.payload)
    new_payload = dict(new.payload)
    # Parameters and financial execution declarations must remain unchanged.
    for name in set(old_payload) | set(new_payload):
        if name != "runtime":
            assert old_payload.get(name) == new_payload.get(name), name
    old_runtime, new_runtime = dict(old.payload["runtime"]), dict(new.payload["runtime"])
    for value in (old_runtime, new_runtime):
        value.pop("source_files")
        value.pop("source_sha256")
    assert old_runtime == new_runtime
    q = cloudpickle.loads((v.WORK / f"{reference}-baseline.pkl").read_bytes())
    parent = next(iter(q.input_bindings.values()))
    ctx = create_research_context(repo, ResearchBatchRef(family),
        resources=ExecutionResources(2, 1, 42), providers=ProviderConfig(bindings={}))
    originals = []
    hashes = {}
    for role, request in parent.plan.requests.items():
        data = ctx.data.fetch(request, prepared=parent.prepared)
        assert data.ready and canonical_frame_sha256(data.dataframe) == data.identity.content_sha256
        originals.append((request, data))
        hashes[role] = data.identity.content_sha256
    for request in q.execution_data.requests.values():
        data = ctx.data.fetch(request, prepared=q.execution_data.prepared)
        assert data.ready and canonical_frame_sha256(data.dataframe) == data.identity.content_sha256
        originals.append((request, data))

    def provider(request):
        matches = []
        for prior, fetched in originals:
            if (request.dataset, request.symbol, request.frequency) != (prior.dataset, prior.symbol, prior.frequency):
                continue
            comparable = normalize_request(request, prior)
            if comparable.parameters != prior.parameters or request.start < prior.start or request.end > prior.end:
                continue
            dates = pd.to_datetime(fetched.dataframe["Date"])
            frame = fetched.dataframe.loc[
                (dates >= pd.Timestamp(request.start)) &
                (dates < pd.Timestamp(request.end) + pd.Timedelta(days=1))
            ].copy().reset_index(drop=True)
            matches.append((frame, dict(fetched.identity.metadata)))
        if not matches:
            raise ValueError(f"No authenticated original input contains request: {request}")
        assert len({canonical_frame_sha256(frame) for frame, _ in matches}) == 1
        return matches[0]

    flows = Dataflows(base_dir=v.ROOT, space=DataSpace(Path("research") / family / "assets/data"),
        providers=ProviderConfig(bindings={dataset: ProviderBinding("published-equivalence-local", "1", provider)
            for dataset in {request.dataset for request, _ in originals}}))
    calendar = ctx.data.fetch(parent.plan.requests[parent.plan.calendar_name], prepared=parent.prepared)
    kwargs = {}
    if "__trading_status" in parent.plan.requests:
        kwargs = {"trading_status": ctx.data.fetch(parent.plan.requests["__trading_status"], prepared=parent.prepared),
                  "status_request": parent.plan.requests["__trading_status"]}
    planned = []
    for label, release, binding, source in (("old", old, old_binding, old_source), ("new", new, new_binding, new_source)):
        instance = StrategyRuntime(repo.strategy_root, dataflows=flows).create(StrategyInit(
            release, parent.plan.tradable_window, v.WORK / "published-runtime" / reference / label,
            source_root=source, runtime_binding=RuntimeBinding.from_dict(binding), pricing=q.execution_data.pricing))
        plan = instance.plan_inputs(calendar, **kwargs)
        requests = {role: normalize_request(request, parent.plan.requests[role]) for role, request in plan.requests.items()}
        assert replace(plan, strategy=parent.plan.strategy, requests=requests) == parent.plan
        planned.append((label, instance, plan))
    union = {repr(request): request for request, _ in originals}
    for _, _, plan in planned:
        union.update({repr(request): request for request in plan.requests.values()})
    prepared = flows.prepare(tuple(union.values()), policy=PreparePolicy.REUSE)
    assert prepared.ready, prepared
    pairs = []
    for label, instance, plan in planned:
        bound = StrategyInputBinding(plan, prepared.reference)
        for role, request in plan.requests.items():
            data = flows.fetch(request, prepared=prepared.reference)
            assert data.ready and data.identity.content_sha256 == hashes[role]
        instance.prepare_data(binding=bound)
        v.save(out / f"{label}_binding.json", bound.to_dict())
        pairs.append((instance, bound))
    modes = {}
    for mode in SignalHistoryMode:
        histories = [instance.inspect_signals(history_mode=mode) for instance, _ in pairs]
        stripped = []
        for (instance, _), history in zip(pairs, histories, strict=True):
            panel = instance.definition.observation.signal_panel
            allowed = set(panel.evidence_fields) if panel else set()
            assert all(name in allowed for name in history if name.startswith("obs_"))
            stripped.append(history.drop(columns=list(allowed & set(history))))
        v.equal_frame(*stripped, {})
        for label, history in zip(("old", "new"), histories, strict=True):
            history.to_csv(out / f"{label}_{mode.value}_signals.csv")
        results = [v.run_account(instance, bound, q.execution_data, mode) for instance, bound in pairs]
        for a, b in zip(results[0][1], results[1][1], strict=True):
            assert a["series"] == b["series"] and a["facts"] == b["facts"]
        v.save(out / f"new_{mode.value}_observations.json", results[1][1])
        mapping, checks = {}, []
        for name in v.NAMES:
            frames = [getattr(result[0], name) for result in results]
            for label, frame in zip(("old", "new"), frames, strict=True):
                frame.to_csv(out / f"{label}_{mode.value}_{name}.csv", index=False)
            compare = [frame.drop(columns=[c for c in frame if c.startswith("obs_")]) if name == "decisions"
                       else frame for frame in frames]
            v.equal_frame(*compare, mapping)
            checks.append({"ledger": name, "rows": len(frames[1]), "comparison": "EXACT_VALUES_ZERO_TOLERANCE"})
        modes[mode.value] = {"status": "PASS", "signal_rows": len(histories[1]), "checks": checks,
                             "fills": len(results[1][0].fills)}
        print(reference, mode.value, "PUBLISHED_EQUIVALENCE_PASS", flush=True)
    artifacts = [{"path": file.name, "sha256": sha256(file.read_bytes()).hexdigest()}
                 for file in sorted(out.iterdir()) if file.is_file()]
    v.save(out / "result.json", {"status": "PASS", "reference": reference,
        "scope": "ARCHIVED_OLD_PACKAGE_VS_INSTALLED_NEW_PACKAGE_PUBLIC_SRT_TXE",
        "old_release_hash": old.release_hash, "new_release_hash": new.release_hash,
        "old_package_hash": old_manifest["package_hash"], "new_package_hash": new_manifest["package_hash"],
        "source_hashes": hashes, "window": v.plain(parent.plan.tradable_window),
        "initial_cash": 100000, "new_data": False, "modes": modes, "artifacts": artifacts})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", choices=tuple(v.ITEMS))
    main(parser.parse_args().reference)
