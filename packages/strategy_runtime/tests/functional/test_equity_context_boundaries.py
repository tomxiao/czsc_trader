"""Public context boundaries retained when avoiding redundant scalar work."""


import pandas as pd
import pytest

from packages.strategy_runtime.tests.context_fixture_support import build, fixture, make_candidate


@pytest.mark.parametrize(
    "bad_time",
    [
        "naive",
    ],
    ids=["SRT-14-C04"],
)
def test_context_rejects_invalid_timestamp_even_outside_visible_prefix(tmp_path, bad_time):
    value, data = make_candidate(tmp_path), fixture()
    auxiliary = data[1].copy(deep=True)
    if bad_time == "naive":
        auxiliary["Date"] = auxiliary.Date.dt.tz_localize(None)
    else:
        auxiliary.loc[2, "Date"] = pd.NaT
    with pytest.raises(ValueError, match="aware finite timestamps"):
        build(value, data, auxiliary_histories={"market": auxiliary})
