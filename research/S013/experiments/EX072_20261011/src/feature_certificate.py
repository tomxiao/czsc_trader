"""Independent C8880-family daily feature certificate; data are caller-supplied.

No runtime/provider/account imports and no data reads, preparation or evaluation.
Supports the unchanged fixed C8880 categories and original thirteen-coordinate domain.
Arithmetic is an independent array/loop implementation, not bitwise pandas emulation.
"""
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from collections.abc import Mapping

import numpy as np
import pandas as pd


class Mechanism(Enum):
    ORIGINAL = "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"
    CURRENT = "RAW_CURRENT_ROUTE_BULL_BOUNDARY_BODY_BEAR_BELOW_RECOVERY"


@dataclass(frozen=True, slots=True)
class C8880Parameters:
    bull_range_window: int
    bull_entry: float
    bull_exit: float
    bull_max_hold: int
    bear_range_window: int
    bear_entry: float
    bear_exit: float
    bear_max_hold: int
    bear_acf_min: float
    regime_window: int
    regime_threshold: float
    confirmation_lookback: int
    confirmation_threshold: float
    mechanism: Mechanism
    exit_on_regime_change: bool

    def __post_init__(self):
        for name, low, high in (
            ("bull_range_window", 21, 360), ("bear_range_window", 21, 360),
            ("bull_max_hold", 1, 60), ("bear_max_hold", 1, 60),
            ("regime_window", 5, 60), ("confirmation_lookback", 40, 120),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(name + " outside original integer domain")
        for name, low, high in (
            ("bull_entry", 0, 1), ("bull_exit", 0, 1), ("bear_entry", 0, 1),
            ("bear_exit", 0, 1), ("bear_acf_min", -.6, .5),
            ("regime_threshold", -.2, .2), ("confirmation_threshold", -.5, .5),
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or not low <= value <= high:
                raise ValueError(name + " outside original finite continuous domain")
        if not (self.bull_entry < self.bull_exit and self.bear_entry < self.bear_exit):
            raise ValueError("original entry/exit feasibility required")
        if type(self.confirmation_threshold) is not float:
            raise TypeError("original confirmation threshold must be a float")
        if type(self.mechanism) is not Mechanism or type(self.exit_on_regime_change) is not bool:
            raise TypeError("typed mechanism and bool regime-exit flag required")
        if self.mechanism is Mechanism.CURRENT and self.exit_on_regime_change:
            raise ValueError("current manager requires explicit False regime exit")

    @classmethod
    def from_parameters(cls, parameters: Mapping):
        if not isinstance(parameters, Mapping) or set(parameters) != {
            "bull", "bear", "regime_window", "regime_threshold", "exit_on_regime_change",
            "confirmation", "context", "mechanism",
        }:
            raise ValueError("exact C8880-family payload keys required")
        if parameters["context"] != {
            "entry_gate": "all", "volume_basis": "ADJUSTED", "weighting": "EQUAL_BLOCKS",
        }:
            raise ValueError("fixed all/ADJUSTED/EQUAL_BLOCKS context required")
        confirmation = parameters["confirmation"]
        if not isinstance(confirmation, Mapping) or set(confirmation) != {
            "enabled", "profile", "threshold", "orientation", "scope", "lookback",
        }:
            raise ValueError("exact confirmation keys required")
        if (confirmation["enabled"] is not True or confirmation["profile"] != "all"
                or type(confirmation["orientation"]) is not int or confirmation["orientation"] != 1
                or confirmation["scope"] != "both" or type(confirmation["threshold"]) is not float):
            raise ValueError("fixed enabled/all/+1/both confirmation and float threshold required")
        for route in ("bull", "bear"):
            p = parameters[route]
            if not isinstance(p, Mapping) or set(p) != {
                "range_window", "entry", "exit", "max_hold", "acf_min", "momentum_min",
                "cooldown", "stop_loss", "trailing_stop", "limit_premium",
            }:
                raise ValueError("exact route keys required")
            if (type(p["cooldown"]) is not int or p["cooldown"] != 0
                    or p["momentum_min"] is not None or p["stop_loss"] is not None
                    or p["trailing_stop"] is not None or p["limit_premium"] != .01):
                raise ValueError("fixed C8880 route categories/1percent limit required")
        if parameters["bull"]["acf_min"] is not None:
            raise ValueError("bull acf_min remains None")
        return cls(
            parameters["bull"]["range_window"], parameters["bull"]["entry"],
            parameters["bull"]["exit"], parameters["bull"]["max_hold"],
            parameters["bear"]["range_window"], parameters["bear"]["entry"],
            parameters["bear"]["exit"], parameters["bear"]["max_hold"], parameters["bear"]["acf_min"],
            parameters["regime_window"], parameters["regime_threshold"],
            confirmation["lookback"], confirmation["threshold"],
            Mechanism(parameters["mechanism"]), parameters["exit_on_regime_change"],
        )

    def parameters(self):
        def route(window, entry, exit, hold, acf):
            return {"range_window": window, "entry": entry, "exit": exit, "max_hold": hold,
                    "acf_min": acf, "momentum_min": None, "cooldown": 0,
                    "stop_loss": None, "trailing_stop": None, "limit_premium": .01}
        return {
            "bull": route(self.bull_range_window, self.bull_entry, self.bull_exit, self.bull_max_hold, None),
            "bear": route(self.bear_range_window, self.bear_entry, self.bear_exit, self.bear_max_hold, self.bear_acf_min),
            "regime_window": self.regime_window, "regime_threshold": self.regime_threshold,
            "exit_on_regime_change": self.exit_on_regime_change, "mechanism": self.mechanism.value,
            "confirmation": {"enabled": True, "profile": "all", "orientation": 1, "scope": "both",
                             "lookback": self.confirmation_lookback, "threshold": self.confirmation_threshold},
            "context": {"entry_gate": "all", "volume_basis": "ADJUSTED", "weighting": "EQUAL_BLOCKS"},
        }


@dataclass(frozen=True, slots=True)
class FeatureCertificateRequest:
    daily: pd.DataFrame
    signal_sessions: tuple[pd.Timestamp, ...]
    parameters: C8880Parameters
    execution: pd.DataFrame | None = None

    def __post_init__(self):
        if type(self.parameters) is not C8880Parameters or not isinstance(self.daily, pd.DataFrame):
            raise TypeError("typed C8880 parameters and caller-supplied daily DataFrame required")
        if type(self.signal_sessions) is not tuple or not self.signal_sessions:
            raise TypeError("nonempty tuple of signal sessions required")
        if not all(type(day) is pd.Timestamp for day in self.signal_sessions):
            raise TypeError("signal sessions must be pandas Timestamp values")
        if self.execution is not None and not isinstance(self.execution, pd.DataFrame):
            raise TypeError("optional execution must be caller-supplied DataFrame")


@dataclass(frozen=True, slots=True)
class FeatureCertificate:
    features: pd.DataFrame
    provenance: Mapping


SOURCE_HASHES = {
    "research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies/range_reversion.py":
        "899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3",
    "research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies/confirmed_range.py":
        "b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a",
    "research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies/boundary_bear_recovery_range.py":
        "3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8",
    "research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies/reentry_confirmed_range.py":
        "6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c",
}
FEATURE_COLUMNS = (
    "Open", "Close", "previous_close", "body_up", "bull_range_position", "bear_range_position",
    "acf20", "momentum20", "regime_momentum", "previous_regime_momentum", "regime", "previous_regime",
    "confirmation_raw_turnover", "confirmation_raw_volume", "confirmation_acf",
    "confirmation_turnover", "confirmation_volume", "confirmation_score",
)
NUMERIC_ATOL = 1e-12
NUMERIC_RTOL = 1e-12


def _frame_arrays(frame, columns):
    if not frame.columns.is_unique or not {"Date", *columns}.issubset(frame.columns):
        raise ValueError("unique columns and complete supplied input required")
    dates = pd.DatetimeIndex(pd.to_datetime(frame.Date, errors="raise")).normalize()
    if dates.tz is not None or dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError("naive unique ordered complete daily dates required")
    values = frame.loc[:, list(columns)].to_numpy(dtype=float, copy=True)
    if not len(values) or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("complete finite positive OHLC/volume/amount required")
    identity = sha256()
    identity.update(json.dumps(list(columns)).encode())
    identity.update(np.asarray(dates.asi8, dtype="<i8").tobytes())
    identity.update(np.asarray(values, dtype="<f8").tobytes())
    return dates, {column: values[:, i] for i, column in enumerate(columns)}, identity.hexdigest()


def _mean_windows(values, width):
    out = np.full(len(values), np.nan)
    for end in range(width - 1, len(values)):
        chunk = values[end - width + 1:end + 1]
        if np.isfinite(chunk).all():
            out[end] = np.mean(chunk)
    return out


def _midrank(values, width):
    """Strict comparisons, complete window including current, exact tie half weight."""
    out = np.full(len(values), np.nan)
    for end in range(width - 1, len(values)):
        chunk = values[end - width + 1:end + 1]
        if np.isfinite(chunk).all():
            current = chunk[-1]
            less = sum(value < current for value in chunk)
            equal = sum(value == current for value in chunk)
            out[end] = (less + equal / 2) / width - .5
    return out


def _acf20(close):
    returns = np.full(len(close), np.nan)
    returns[1:] = close[1:] / close[:-1] - 1
    out = np.full(len(close), np.nan)
    for end in range(20, len(close)):
        window = returns[end - 19:end + 1]
        centered = window - np.mean(window)
        variance = np.mean(centered * centered)
        # Exact source's np.isclose(variance,0): rtol*0 vanishes; default atol=1e-8.
        if abs(variance) > 1e-8:
            lag_energy = np.dot(centered[:-1], centered[1:])
            out[end] = lag_energy / 19 / variance
    return out


def _range(close, high, low, width):
    out = np.full(len(close), np.nan)
    for end in range(width - 1, len(close)):
        begin = end - width + 1
        floor, ceiling = np.min(low[begin:end + 1]), np.max(high[begin:end + 1])
        if ceiling != floor:
            # Preserve original inconsistent OHLC observations and values outside0..1; never repair/clip.
            out[end] = (close[end] - floor) / (ceiling - floor)
    return out


def certify_features(request: FeatureCertificateRequest) -> FeatureCertificate:
    if type(request) is not FeatureCertificateRequest:
        raise TypeError("FeatureCertificateRequest required")
    dates, values, daily_hash = _frame_arrays(request.daily, ("Open", "Close", "High", "Low", "Volume", "Amount"))
    sessions = pd.DatetimeIndex(request.signal_sessions)
    if (sessions.tz is not None or sessions.hasnans or not sessions.is_unique
            or not sessions.is_monotonic_increasing or not sessions.equals(sessions.normalize())):
        raise ValueError("naive unique ordered normalized signal dates required")
    selected = dates.get_indexer(sessions)
    if (selected < 0).any():
        raise ValueError("every requested signal must exist in independent daily input")
    execution_hash = None
    if request.execution is not None:
        raw_dates, raw, execution_hash = _frame_arrays(request.execution, ("Close", "Volume", "Amount"))
        locations = dates.get_indexer(raw_dates)
        if (locations < 0).any():
            raise ValueError("raw execution dates must share adjusted calendar")
        reconstructed = values["Volume"][locations] * values["Close"][locations] / raw["Close"]
        if not np.allclose(reconstructed, raw["Volume"], rtol=1e-12, atol=1e-6):
            raise ValueError("per-date raw/HFQ volume conversion differs")
        if not np.allclose(values["Amount"][locations], raw["Amount"], rtol=1e-12, atol=1e-6):
            raise ValueError("amount must be invariant across price-unit conversion")
    p, close = request.parameters, values["Close"]
    acf = _acf20(close)
    momentum20, regime_momentum = np.full(len(dates), np.nan), np.full(len(dates), np.nan)
    momentum20[20:] = close[20:] / close[:-20] - 1
    regime_momentum[p.regime_window:] = close[p.regime_window:] / close[:-p.regime_window] - 1
    previous_momentum = np.concatenate(([np.nan], regime_momentum[:-1]))
    previous_close = np.concatenate(([np.nan], close[:-1]))
    turnover = values["Amount"] / _mean_windows(values["Amount"], 20)
    log_delta = np.full(len(dates), np.nan)
    log_volume = np.log(values["Volume"])
    log_delta[1:] = log_volume[1:] - log_volume[:-1]
    volume_change = _mean_windows(log_delta, 20)
    acf_rank = _midrank(acf, p.confirmation_lookback)
    turnover_rank = _midrank(turnover, p.confirmation_lookback)
    volume_rank = _midrank(volume_change, p.confirmation_lookback)
    frame = pd.DataFrame({
        "Open": values["Open"], "Close": close, "previous_close": previous_close,
        "body_up": close > values["Open"],
        "bull_range_position": _range(close, values["High"], values["Low"], p.bull_range_window),
        "bear_range_position": _range(close, values["High"], values["Low"], p.bear_range_window),
        "acf20": acf, "momentum20": momentum20,
        "regime_momentum": regime_momentum, "previous_regime_momentum": previous_momentum,
        "regime": np.where(regime_momentum >= p.regime_threshold, "bull", "bear"),
        "previous_regime": np.where(previous_momentum >= p.regime_threshold, "bull", "bear"),
        "confirmation_raw_turnover": turnover, "confirmation_raw_volume": volume_change,
        "confirmation_acf": acf_rank, "confirmation_turnover": turnover_rank,
        "confirmation_volume": volume_rank,
        "confirmation_score": .5 * acf_rank + .25 * turnover_rank + .25 * volume_rank,
    }, index=dates).iloc[selected].copy()
    numeric = frame.select_dtypes(include=[np.number])
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("requested independent feature history undefined: warmup, ACF variance, or range denominator")
    parameter_hash = sha256(json.dumps(p.parameters(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result_hash = sha256(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()).hexdigest()
    provenance = {
        "status": "SOURCE_ONLY_CERTIFICATE", "scope": "C8880 fixed categories/original13 domain only",
        "daily_required_columns_sha256": daily_hash, "execution_required_columns_sha256": execution_hash,
        "parameters_sha256": parameter_hash, "features_content_sha256": result_hash,
        "formula_source_hashes": dict(SOURCE_HASHES), "certificate_implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "score_independent": True, "previous_regime_independent": True,
        "raw_volume_check": "CHECKED" if request.execution is not None else "NOT_REQUESTED",
        "volume_basis_used": "ADJUSTED", "numeric_atol": NUMERIC_ATOL, "numeric_rtol": NUMERIC_RTOL,
        "rank_ties": "Exact source strict < and ==; no epsilon merge. Floating raw-stat differences can change ranks at numerical near-ties; any native mismatch requires explicit review, never silent replacement.",
        "boundaries": "Provenance covers supplied required-column bytes, not a public asset/account identity. No source fetch, asset load, account or certification of economic results. Full signal-state oracle remains separate.",
        "OHLC_policy": "Finite positive inputs required; no high/low consistency repair or range clipping.",
    }
    return FeatureCertificate(frame, provenance)
