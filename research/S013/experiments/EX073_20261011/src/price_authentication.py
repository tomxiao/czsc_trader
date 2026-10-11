"""Only fixed native anchor price-unit authentication; no fallback or new labels."""

import numpy as np
import pandas as pd
import entry_core as core


def authenticate_price_units(prices, warm, anchor, index):
    if type(anchor) is not float or anchor != 0.2803:
        raise ValueError("original authenticated S013 anchor .2803 required")
    common_dates = prices.index.intersection(warm.index)
    if not len(common_dates):
        raise ValueError("original public price overlap required")
    # SRT research units are HFQ prices / anchor_factor, not raw provider HFQ units.
    np.testing.assert_allclose(
        prices.loc[common_dates, ["Open", "Close"]].to_numpy() * anchor,
        warm.loc[common_dates, ["Open", "Close"]].to_numpy(),
        rtol=0,
        atol=5e-15,
    )
    original = core.labels(prices, index)
    scaled = core.labels(prices * anchor, index)
    cols = ["first2", "late_return", "full4", "late_downside"]
    np.testing.assert_allclose(original[cols], scaled[cols], rtol=0, atol=5e-15, equal_nan=True)
    pd.testing.assert_frame_equal(
        original.drop(columns=cols), scaled.drop(columns=cols), check_exact=True
    )
    return {
        "anchor_factor": anchor,
        "price_units": "native HFQ_RESEARCH=public HFQ/anchor_factor",
        "public_hfq_overlap_rows": len(common_dates),
        "all_label_scale_rows": len(index),
        "all_labels_and_maturity_scale_invariant": True,
        "tolerance_unchanged": "rtol0/atol5e-15",
    }
