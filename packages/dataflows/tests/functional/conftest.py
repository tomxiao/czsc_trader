"""Test-only helpers for exercising publication checks through two-phase DFLS."""

from itertools import count
from pathlib import Path

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


@pytest.fixture
def flow_factory(tmp_path):
    spaces = count()

    def create(providers=None):
        bindings = None if providers is None else {
            Dataset(dataset): ProviderBinding(name="fixture", revision="v1", fetch=provider)
            for dataset, provider in providers.items()
        }
        return Dataflows(
            base_dir=tmp_path,
            space=DataSpace(path=Path(f"space-{next(spaces)}")),
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
