import pytest

from research_experiment import ExperimentBinding

@pytest.mark.parametrize("schema", [1, True, "3", 4])
def test_retired_binding_is_rejected_before_loading_source(schema):
    with pytest.raises(ValueError, match="schema_version must be 3"):
        ExperimentBinding(schema, "experiment", "Experiment", ("experiment.py",), "a" * 64, ())
