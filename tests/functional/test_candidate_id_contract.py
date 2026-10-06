import pytest
from strategy_manager import ValidationError as RegistryValidationError

from czsc_trader.research_tools.context import ResearchBatchRef, ExperimentRef

@pytest.mark.parametrize("family", ['S01', 'S0011', 'S０１１', ' S011', 'S011 '])
def test_research_owner_family_is_canonical(family):
    with pytest.raises(RegistryValidationError):
        ResearchBatchRef(family)
    with pytest.raises(RegistryValidationError):
        ExperimentRef(family, "EX001_20261002")

def test_research_owners_need_no_dummy_candidate():
    assert ResearchBatchRef("S011").strategy_id == "S011"
    assert ExperimentRef("S011", "EX001_20261002").strategy_id == "S011"
