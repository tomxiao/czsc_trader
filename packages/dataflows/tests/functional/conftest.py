"""Test-only helpers for exercising publication checks through two-phase DFLS."""

from itertools import count
from hashlib import sha256
from pathlib import Path
from shutil import copytree
from uuid import uuid4

import pandas as pd
import pytest

from dataflows import (
    Dataflows,
    DataResult,
    DataSpace,
    Dataset,
    PreparePolicy,
    ProviderBinding,
    ProviderConfig,
)
from dataflows.history_repair import frame_content_sha256
from dataflows.ohlcv_quality import build_quality_evidence


def ohlcv_fixture_metadata(
    daily, *, start, end, intraday=None, frequency="daily", listing_date="2013-01-01",
    market="a_share",
):
    """Explicit synthetic calendar and lifecycle, independent of returned rows.

    Callers supply the complete daily anchor and, for minutes, the independently
    declared full-session source even when testing a partial returned slice.
    """
    dates = pd.date_range(start, end).normalize()
    expected = dates[(dates.dayofweek < 5) & (dates >= pd.Timestamp(listing_date))]
    sessions = expected.strftime("%Y-%m-%d").tolist()
    calendar = pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"),
                             "is_open": (dates.dayofweek < 5).astype(int)})
    return {
        "daily_session_coverage": {
            "source": "declared-synthetic-weekday-calendar",
            "exchange": "HKEX" if market == "hk" else "SSE",
            "start_date": dates[0].date().isoformat(), "end_date": dates[-1].date().isoformat(),
            "listing_date": listing_date, "listing_source": "declared-synthetic-lifecycle",
            "expected_dates": sessions, "verified_sessions": len(sessions),
            "calendar": calendar.to_dict("records"),
            "calendar_sha256": frame_content_sha256(calendar),
        },
        "ohlcv_quality_evidence": build_quality_evidence(
            daily, intraday=intraday, frequency=frequency, expected_dates=sessions, market=market,
        ),
    }


@pytest.fixture(scope="session")
def empty_space_seeds(frozen_seed_root):
    """Reuse real empty schemas, never an open connection or mutable test space.

    Storage initialization, corrupt spaces and concurrent creation are exercised
    directly in test_data_space. Dataset tests still run every prepare/fetch and
    publication transaction against a private copy. Separate factory calls in
    one case retain distinct space identities without rewriting any identity.
    """
    base = frozen_seed_root / "dfls-empty-spaces"
    seeds = {}

    def seed(index):
        if index not in seeds:
            space = DataSpace(Path(f"space-{index}"))
            Dataflows(base_dir=base, space=space, providers=ProviderConfig(bindings={}))
            path = base / space.path
            seeds[index] = path, sha256((path / "assets.sqlite3").read_bytes()).hexdigest()
        return seeds[index][0]

    yield seed
    for path, digest in seeds.values():
        assert sha256((path / "assets.sqlite3").read_bytes()).hexdigest() == digest


@pytest.fixture
def empty_space_factory(tmp_path, empty_space_seeds):
    """Give dataset fixtures named private stores without redoing schema setup.

    Repeat opens retain the same identity; distinct names within one case use
    distinct original seed identities. No identity or database bytes are edited.
    """
    spaces = {}

    def create(name):
        space = DataSpace(Path(name))
        if space.path not in spaces:
            copytree(empty_space_seeds(len(spaces)), tmp_path / space.path)
            spaces[space.path] = space
        return space

    return create


@pytest.fixture
def flow_factory(tmp_path, empty_space_factory):
    spaces = count()

    def create(providers=None):
        index = next(spaces)
        space = empty_space_factory(f"space-{index}")
        bindings = None if providers is None else {
            Dataset(dataset): ProviderBinding(name="fixture", revision="v1", fetch=provider)
            for dataset, provider in providers.items()
        }
        return Dataflows(
            base_dir=tmp_path,
            space=space,
            providers=ProviderConfig(bindings=bindings),
        )

    return create


@pytest.fixture
def publish_data():
    """Preserve validation assertions while exercising prepare and pinned fetch."""
    def publish(flows, request):
        prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
        if prepared.ready:
            return flows.fetch(request, prepared=prepared.reference)
        item, = prepared.items
        return DataResult(status=item.status, error=item.error)

    return publish


@pytest.fixture(scope="module")
def publication_seeds(frozen_seed_root):
    """Build each immutable baseline through the real public publication path."""
    # Reuse only the repository-managed temporary root and its Windows ACLs.
    base = frozen_seed_root / f"dfls-publications-{uuid4().hex}"
    base.mkdir()
    seeds = {}

    def seed(key, bindings, request):
        if key not in seeds:
            flow = Dataflows(base_dir=base, space=DataSpace(Path(key)),
                             providers=ProviderConfig(bindings=bindings))
            prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
            assert prepared.ready, prepared.items
            seeds[key] = (base / key, request, prepared.reference)
        path, original_request, reference = seeds[key]
        assert original_request == request, "a publication seed must have one request contract"
        return path, reference

    return seed


@pytest.fixture
def clone_published_flow(tmp_path, publication_seeds):
    """Each case gets a private copy; no mutable Dataflows/store is shared by cases.

    The copied space identity intentionally refers to the same baseline publication.
    Space identity/concurrency tests continue to create genuinely new spaces.
    """
    def clone(key, providers, request):
        bindings = None if providers is None else {
            Dataset(dataset): ProviderBinding(name="fixture", revision="v1", fetch=provider)
            for dataset, provider in providers.items()
        }
        path, reference = publication_seeds(key, bindings, request)
        copytree(path, tmp_path / key)
        flow = Dataflows(base_dir=tmp_path, space=DataSpace(Path(key)),
                         providers=ProviderConfig(bindings=bindings))
        original = flow.fetch(request, prepared=reference)
        assert original.ready, original.error
        return flow, original

    return clone
