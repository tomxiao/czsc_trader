import pytest
from strategy_manager import ValidationError as RegistryValidationError

from czsc_trader.research_tools.delivery import MandateOwner, ExperimentOwner

@pytest.mark.parametrize("family", ['S01', 'S0011', 'S０１１', ' S011', 'S011 '])
def test_delivery_owner_family_is_canonical(family):
    with pytest.raises(RegistryValidationError):
        MandateOwner(family)
    with pytest.raises(RegistryValidationError):
        ExperimentOwner(family, f"20261002_{family}_EX01")

def test_family_delivery_owners_need_no_dummy_candidate():
    assert MandateOwner("S011").strategy_id == "S011"
    assert ExperimentOwner("S011", "20261002_S011_EX01").strategy_id == "S011"
