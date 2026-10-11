"""Single-coordinate signal-feature substitutions; no state propagation or cash.

Only the ORIGINAL_TIME contract is supported by this mapping. The caller must
authenticate same-input native features and their parameter bindings. Window
and lookback values are not stored in Feature: their numerical provenance must
be checked by the driver. Range positions use full-daily High/Low windows;
score uses the original full confirmation formula. Neither is recomputed here.
"""
from dataclasses import replace

from transition import Feature, ROUTES


COORDINATES = (
    ('bull.range_window', 21., 360., 'INTEGER'),
    ('bull.entry', 0., 1., 'CONTINUOUS'),
    ('bull.exit', 0., 1., 'CONTINUOUS'),
    ('bull.max_hold', 1., 60., 'INTEGER'),
    ('bear.range_window', 21., 360., 'INTEGER'),
    ('bear.entry', 0., 1., 'CONTINUOUS'),
    ('bear.exit', 0., 1., 'CONTINUOUS'),
    ('bear.max_hold', 1., 60., 'INTEGER'),
    ('bear.acf_min', -.6, .5, 'CONTINUOUS'),
    ('regime_window', 5., 60., 'INTEGER'),
    ('regime_threshold', -.2, .2, 'CONTINUOUS'),
    ('confirmation.lookback', 40., 120., 'INTEGER'),
    ('confirmation.threshold', -.5, .5, 'CONTINUOUS'),
)
COORDINATE_NAMES = tuple(row[0] for row in COORDINATES)
INVARIANT_FIELDS = ('signal_close', 'previous_signal_close', 'bull_acf_value', 'bear_acf_value')


def hybrid(centerFeature: Feature, pointFeature: Feature, coordinate: str,
           rawrouteWindowOnly: str | None = None,
           rawrouteThresholdOnly: str | None = None) -> Feature:
    """Return base with one numerical coordinate taken from source.

Names centerFeature/pointFeature express forward use, but the first argument
always means BASE and the second SOURCE. Reverse use swaps them. The W-only
route must use source W with BASE threshold; threshold-only route must use
BASE W with source threshold, both Close/Close.shift(W)-1 >= threshold. Thus
reverse needs its own recomputed routes, not the forward routes reversed.

No coordinate alters observed state, age, anchor or execution. A single entry
or exit replacement violating entry<exit raises, rather than clipping,
replacing both coordinates or silently omitting the observation. Integer
rounding/unchanged coordinates are preserved by the authenticated driver.
"""
    if not isinstance(centerFeature, Feature) or not isinstance(pointFeature, Feature):
        raise TypeError('typed base/source Feature required')
    if type(coordinate) is not str or coordinate not in COORDINATE_NAMES:
        raise ValueError('one original13 coordinate required')
    if any(getattr(centerFeature, name) != getattr(pointFeature, name) for name in INVARIANT_FIELDS):
        raise ValueError('same signal prices and unchanged raw ACF20 required')
    if centerFeature.bull_rule.acf_min is not None or pointFeature.bull_rule.acf_min is not None:
        raise ValueError('original inactive bull ACF threshold must remain null')
    for route in (rawrouteWindowOnly, rawrouteThresholdOnly):
        if route is not None and route not in ROUTES:
            raise ValueError('recomputed raw route must be bull or bear')
    if coordinate == 'regime_window':
        if rawrouteWindowOnly is None:
            raise ValueError('source W with base threshold route required')
        return replace(centerFeature, raw_route=rawrouteWindowOnly)
    if coordinate == 'regime_threshold':
        if rawrouteThresholdOnly is None:
            raise ValueError('base W with source threshold route required')
        return replace(centerFeature, raw_route=rawrouteThresholdOnly)
    if coordinate == 'confirmation.lookback':
        return replace(centerFeature, confirmation_score=pointFeature.confirmation_score)
    if coordinate == 'confirmation.threshold':
        return replace(centerFeature, confirmation_threshold=pointFeature.confirmation_threshold)
    route, attribute = coordinate.split('.')
    if attribute == 'range_window':
        name = route + '_range_position'
        return replace(centerFeature, **{name: getattr(pointFeature, name)})
    name = route + '_rule'
    rule = replace(getattr(centerFeature, name), **{attribute: getattr(getattr(pointFeature, name), attribute)})
    return replace(centerFeature, **{name: rule})
