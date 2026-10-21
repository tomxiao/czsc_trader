"""Prospectively fixed business coordinates; no account performance is consumed."""
from strategy_evaluator import ParameterCoordinate,ParameterCoordinateKind


def coordinates(parameters):
    p=parameters
    continuous=ParameterCoordinateKind.CONTINUOUS
    integer=ParameterCoordinateKind.INTEGER
    specs=[('entry',0.,.03,continuous)]
    if p['max_days']>1:
        specs.append(('exit',0.,.02,continuous))
    specs.append(('max_days',1.,20.,integer))
    if 'range_cap' in p:
        if p['range_cap']>0:
            specs.append(('range_cap',0.,4.,continuous))
    elif p['sizing']=='constant':
        specs.append(('low_weight',0.,1.,continuous))
    elif p['sizing'] in ('relative','absolute'):
        specs.extend([('threshold',0.,4. if p['sizing']=='relative' else 2/9,continuous),
                      ('low_weight',0.,1.,continuous)])
    return tuple(ParameterCoordinate(name,float(p[name]),lower,upper,kind) for name,lower,upper,kind in specs)


def materialize(parameters,space,values):
    updated=dict(parameters)
    for coord,value in zip(space.coordinates,values,strict=True):
        updated[coord.name]=int(value) if coord.kind is ParameterCoordinateKind.INTEGER else float(value)
    return updated
