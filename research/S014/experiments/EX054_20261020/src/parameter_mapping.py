"""Prospective business coordinates; no market or account outcomes are read."""

COORDINATES = (
    # name, center, lower, upper, kind. Windows are trading sessions.
    ("support_window", 5, 2, 30, "INTEGER"),
    ("warmup_sessions", 60, 30, 252, "INTEGER"),
    ("holding_horizon", 10, 2, 40, "INTEGER"),
    ("trend_window", 20, 5, 80, "INTEGER"),
    ("trend_lag", 5, 1, 30, "INTEGER"),
    ("atr_window", 20, 5, 80, "INTEGER"),
    ("shock_window", 5, 1, 30, "INTEGER"),
    ("volatility_window", 20, 5, 80, "INTEGER"),
    ("shock_z", 2.0, 0.5, 4.0, "CONTINUOUS"),
    ("cost_atr", 1.0, 0.25, 3.0, "CONTINUOUS"),
)


def map_coordinates(coordinates):
    if len(coordinates) != len(COORDINATES):
        raise ValueError("Coordinate width differs")
    return {"permission_profile": "AGE_PRIOR_TREND_PERMISSION",
            **{name: int(value) if kind == "INTEGER" else float(value)
               for (name, _, _, _, kind), value in zip(COORDINATES, coordinates, strict=True)}}
