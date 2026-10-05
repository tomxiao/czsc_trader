"""Fixed own-price competing explanation for peer confirmation."""

import numpy as np
import pandas as pd

BASES = (
    "o01",
    "mid_momentum_positive",
    "o01_own_positive",
    "o01_own_nonpositive",
    "mid_momentum_positive_own_positive",
    "mid_momentum_positive_own_nonpositive",
)
GATES = ("own_intraday_positive", "peer_positive")
PAIRS = {b: GATES if b in BASES[:2] else ("peer_positive",) for b in BASES}


def make_inputs(d, f, inherited, inherited_valid, peer_gate, peer_valid):
    own = d.Close / d.Open - 1
    np.testing.assert_allclose(own, f.intraday, atol=1e-12, rtol=1e-12)
    defined = np.isfinite(own)
    signals = inherited.copy()
    valids = inherited_valid.copy()
    for base in BASES[:2]:
        for suffix, test in (("positive", own.gt(0)), ("nonpositive", own.le(0))):
            name = base + "_own_" + suffix
            valids[name] = inherited_valid[base] & defined
            signals[name] = inherited[base] & test & valids[name]
    gates = pd.DataFrame(
        {"own_intraday_positive": own.gt(0) & defined, "peer_positive": peer_gate}, index=d.index
    )
    valid = pd.DataFrame(
        {"own_intraday_positive": defined, "peer_positive": peer_valid}, index=d.index
    )
    return signals, valids, gates, valid


def nonoverlap(mask, spacing):
    result = []
    next_index = 0
    for index in np.flatnonzero(np.asarray(mask)):
        if index >= next_index:
            result.append(int(index))
            next_index = int(index) + spacing
    return np.asarray(result, dtype=int)
