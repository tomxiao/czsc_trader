"""Public evaluation must reject actual purchased data missing the cutoff."""

from dataclasses import replace
import pandas as pd
import pytest
from czsc_trader.research_tools import evaluate_strategy
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def test_formal_evaluation_rejects_data_that_stops_before_development_cutoff(managed_evaluation):
    _, request = managed_evaluation
    data = request.execution_data
    cutoff = pd.Timestamp(request.data_cutoff)
    stale = replace(data,
        adjusted_daily=data.adjusted_daily.loc[data.adjusted_daily.dt.lt(cutoff)].copy(),
        execution_daily=data.execution_daily.loc[data.execution_daily.dt.lt(cutoff)].copy(),
    )
    with pytest.raises(ValueError, match="execution evaluation sessions are incomplete"):
        evaluate_strategy(replace(request, execution_data=stale, input_bindings={}))
