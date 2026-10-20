"""Pure ex-ante parameter constraints; no performance screening."""


def feasible(coordinates):
    support, warmup, horizon, trend, lag, atr, shock, vol, z, stop = coordinates
    return bool(warmup >= max(support, trend + lag, atr, shock + vol)
                and horizon >= 2 and z > 0 and stop > 0)
