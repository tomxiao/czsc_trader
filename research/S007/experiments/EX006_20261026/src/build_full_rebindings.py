"""Rebind current frozen and display-upgrade sources to one authenticated full window."""

from pathlib import Path
from dataclasses import replace
import argparse
import json
import cloudpickle
import pandas as pd
import shutil
from czsc_trader.application import (
    RepositoryContext,
    create_research_context,
    validate_release_package,
)
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources
from strategy_runtime import (
    StrategyCandidate,
    StrategyRelease,
    StrategyRuntime,
    StrategyInit,
    StrategyInputBinding,
    implementation_sha256,
)
from dataflows import (
    Dataflows,
    DataSpace,
    ProviderBinding,
    ProviderConfig,
    PreparePolicy,
    canonical_frame_sha256,
    EvidenceParameters,
)

ROOT = Path(__file__).resolve().parents[5]


def main(family):
    ref = family + "-v1"
    work = json.loads((ROOT / ".tmp/observation-v4-upgrade/work.json").read_text(encoding="utf-8"))[
        ref
    ]
    home = ROOT / work["home"]
    source = ROOT / work["source"]
    request = cloudpickle.loads(
        (ROOT / ".tmp/observation-v4-upgrade" / f"{ref}-baseline.pkl").read_bytes()
    )
    original_binding = request.input_bindings["full"]
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(
        repo, ResearchBatchRef(family), resources=ExecutionResources(2, 1, 42)
    )
    original = json.loads(
        (ROOT / "strategies" / family / "versions/v1.json").read_text(encoding="utf-8")
    )
    old = StrategyRelease.from_mapping(original)
    payload = json.loads(json.dumps(original["strategy_payload"]))
    install = validate_release_package(repo, ref)[1]["install_files"]
    payload["runtime"]["source_files"] = list(
        dict.fromkeys(
            payload["runtime"]["source_files"]
            + install
            + ["strategies/observation_explanation_v4.py"]
        )
    )
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=source
    )
    child = StrategyCandidate(family, "C9950", payload, source)
    originals = []
    hashes = {}
    execution_hashes = {}
    for role, req in original_binding.plan.requests.items():
        fetched = ctx.data.fetch(req, prepared=original_binding.prepared)
        if (
            not fetched.ready
            or canonical_frame_sha256(fetched.dataframe) != fetched.identity.content_sha256
        ):
            raise ValueError("parent input is not authenticated")
        originals.append((req, fetched))
        hashes[role] = fetched.identity.content_sha256

    for role, req in request.execution_data.requests.items():
        fetched = ctx.data.fetch(req, prepared=request.execution_data.prepared)
        if (
            not fetched.ready
            or canonical_frame_sha256(fetched.dataframe) != fetched.identity.content_sha256
        ):
            raise ValueError("execution input is not authenticated")
        originals.append((req, fetched))
        execution_hashes[role] = fetched.identity.content_sha256

    def provider(req):
        matches = []
        for prior, fetched in originals:
            if (req.dataset, req.symbol, req.frequency) != (
                prior.dataset,
                prior.symbol,
                prior.frequency,
            ):
                continue
            comparable = req
            if isinstance(req.parameters, EvidenceParameters) and isinstance(
                prior.parameters, EvidenceParameters
            ):
                comparable = replace(
                    req,
                    parameters=replace(
                        req.parameters, repository_root=prior.parameters.repository_root
                    ),
                )
            if (
                comparable.parameters != prior.parameters
                or req.start < prior.start
                or req.end > prior.end
            ):
                continue
            days = pd.to_datetime(fetched.dataframe["Date"])
            frame = (
                fetched.dataframe.loc[
                    (days >= pd.Timestamp(req.start))
                    & (days < pd.Timestamp(req.end) + pd.Timedelta(days=1))
                ]
                .copy()
                .reset_index(drop=True)
            )
            matches.append((frame, dict(fetched.identity.metadata)))
        if not matches:
            raise ValueError(f"Requested asset has no authenticated containing input: {req}")
        if len({canonical_frame_sha256(frame) for frame, _ in matches}) != 1:
            raise ValueError(
                f"Authenticated runtime/execution inputs disagree on shared rows: {req}"
            )
        return matches[0]

    flows = Dataflows(
        base_dir=ROOT,
        space=DataSpace(Path("research") / family / "assets/data"),
        providers=ProviderConfig(
            bindings={
                dataset: ProviderBinding(f"{family.lower()}-v4-authenticated-full", "1", provider)
                for dataset in {req.dataset for req, _ in originals}
            }
        ),
    )
    cal = ctx.data.fetch(
        original_binding.plan.requests[original_binding.plan.calendar_name],
        prepared=original_binding.prepared,
    )
    kwargs = {}
    if "__trading_status" in original_binding.plan.requests:
        kwargs = {
            "trading_status": ctx.data.fetch(
                original_binding.plan.requests["__trading_status"],
                prepared=original_binding.prepared,
            ),
            "status_request": original_binding.plan.requests["__trading_status"],
        }
    pairs = []
    for name, src in [("old", old), ("new", child)]:
        instance = StrategyRuntime(repo.strategy_root, dataflows=flows).create(
            StrategyInit(
                src,
                original_binding.plan.tradable_window,
                ROOT / ".tmp/observation-v4-upgrade" / f"{ref}-full-{name}",
                pricing=request.execution_data.pricing,
            )
        )
        plan = instance.plan_inputs(cal, **kwargs)
        normalized = {}
        for role, req in plan.requests.items():
            prior = original_binding.plan.requests[role]
            if isinstance(req.parameters, EvidenceParameters) and isinstance(
                prior.parameters, EvidenceParameters
            ):
                req = replace(
                    req,
                    parameters=replace(
                        req.parameters, repository_root=prior.parameters.repository_root
                    ),
                )
            normalized[role] = req
        assert (
            replace(plan, strategy=original_binding.plan.strategy, requests=normalized)
            == original_binding.plan
        )
        pairs.append((name, instance, plan))
    union = {repr(req): req for req in original_binding.plan.requests.values()}
    for _, _, plan in pairs:
        union.update({repr(req): req for req in plan.requests.values()})
    union.update({repr(req): req for req in request.execution_data.requests.values()})
    prepared = flows.prepare(tuple(union.values()), policy=PreparePolicy.REUSE)
    if not prepared.ready:
        raise ValueError(str(prepared))
    result = {
        "reference": ref,
        "status": "PASS",
        "source_parent_binding": original_binding.to_dict(),
        "source_hashes": hashes,
        "execution_source_hashes": execution_hashes,
        "execution_source_prepared": {
            "space_id": str(request.execution_data.prepared.space_id),
            "preparation_id": str(request.execution_data.prepared.preparation_id),
            "manifest_sha256": request.execution_data.prepared.manifest_sha256,
        },
        "allowed_difference": "Only EvidenceParameters.repository_root; source_path, sha256, request bounds, and all other plan facts remain exact.",
    }
    for name, instance, plan in pairs:
        binding = StrategyInputBinding(plan, prepared.reference)
        for role, req in plan.requests.items():
            actual = flows.fetch(req, prepared=prepared.reference)
            assert actual.ready and actual.identity.content_sha256 == hashes[role]
        instance.prepare_data(binding=binding)
        result[name] = binding.to_dict()
    for role, req in request.execution_data.requests.items():
        actual = flows.fetch(req, prepared=prepared.reference)
        assert actual.ready and actual.identity.content_sha256 == execution_hashes[role]
    previous = home / "others/full_window_rebindings.json"
    if previous.exists():
        archive = home / "others/preparations_before_execution_union"
        archive.mkdir(exist_ok=True)
        archived = archive / previous.name
        if not archived.exists():
            shutil.copy2(previous, archived)
    (home / "others/full_window_rebindings.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(ref, "FULL_WINDOW_REBINDING_PASS", len(union), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("family", choices=["S003", "S007"])
    main(parser.parse_args().family)
