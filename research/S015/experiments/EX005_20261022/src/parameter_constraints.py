"""Only structural parameter feasibility; no market or return-dependent acceptance."""


def feasible(names,values):
    return bool(all(value>0 for name,value in zip(names,values,strict=True) if name in ('range_cap','threshold')))
