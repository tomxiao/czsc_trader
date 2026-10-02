"""Explicit BuyHold execution policies, shared by TDR requests and handoffs."""

from dataclasses import asdict, dataclass
import math

from strategy_runtime import canonical_sha256


BENCHMARK_EXECUTION_VERSION = "buyhold-execution-v1"


def _lot(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("lot_size must be a positive integer")


@dataclass(frozen=True)
class NextOpenBuyHold:
    lot_size: int

    def __post_init__(self):
        _lot(self.lot_size)


@dataclass(frozen=True)
class LimitBuyHold:
    lot_size: int
    premium: float
    price_tick: float
    price_limit_ratio: float
    maximum_order_quantity: int

    def __post_init__(self):
        _lot(self.lot_size)
        if self.lot_size % 100:
            raise ValueError("limit lot_size must be a multiple of SRT's 100-share lot")
        for name in ("premium", "price_tick", "price_limit_ratio"):
            value = getattr(self, name)
            if type(value) is not float or not math.isfinite(value):
                raise TypeError(f"{name} must be a finite float")
        if not 0 <= self.premium < self.price_limit_ratio < 1 or self.price_tick <= 0:
            raise ValueError("invalid BuyHold premium, tick or price limit")
        if (
            type(self.maximum_order_quantity) is not int
            or self.maximum_order_quantity < self.lot_size
            or self.maximum_order_quantity % self.lot_size
        ):
            raise ValueError("maximum_order_quantity must contain whole positive lots")


@dataclass(frozen=True)
class EvaluationBenchmark:
    execution: NextOpenBuyHold | LimitBuyHold

    def __post_init__(self):
        if type(self.execution) not in (NextOpenBuyHold, LimitBuyHold):
            raise TypeError("benchmark requires a typed BuyHold execution policy")

    @property
    def benchmark_id(self) -> str:
        return "BuyHold"

    @property
    def kind(self) -> str:
        return "BUYHOLD"

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "kind": self.kind,
            "execution_version": BENCHMARK_EXECUTION_VERSION,
            "execution": {"type": type(self.execution).__name__, **asdict(self.execution)},
        }

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {
            "benchmark_id",
            "kind",
            "execution_version",
            "execution",
        }:
            raise ValueError("benchmark fields differ from schema")
        raw = value["execution"]
        if type(raw) is not dict or raw.get("type") not in ("NextOpenBuyHold", "LimitBuyHold"):
            raise ValueError("unknown BuyHold execution policy")
        policy = NextOpenBuyHold if raw["type"] == "NextOpenBuyHold" else LimitBuyHold
        result = cls(policy(**{k: v for k, v in raw.items() if k != "type"}))
        if result.to_dict() != value:
            raise ValueError("benchmark identity or execution version differs")
        return result
