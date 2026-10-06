"""Host binding exposes stable identity without a writable storage handle."""
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import UUID

import pytest
from dataflows import Dataflows, DataSpace, DataSpaceBinding, ProviderConfig


def test_space_binding_is_typed_immutable_and_stable_when_reopened(tmp_path):
    space = DataSpace(Path("research/S900/data"))
    flows = Dataflows(base_dir=tmp_path, space=space, providers=ProviderConfig(bindings={}))
    binding = flows.binding
    assert type(binding) is DataSpaceBinding
    assert binding.base_dir == tmp_path.resolve() and binding.space == space
    assert isinstance(binding.space_id, UUID)
    reopened = Dataflows(base_dir=tmp_path, space=space, providers=ProviderConfig(bindings={}))
    assert reopened.binding == binding
    with pytest.raises(FrozenInstanceError):
        binding.space_id = UUID(int=0)
