"""Compare replay evidence without rewriting original identities or ledger facts."""

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from datetime import date
from enum import StrEnum
import math
import json

from .models import Record
from .replay_audit import ReplayEvidence, hash_replay_evidence


class LedgerComparisonMode(StrEnum):
    STRICT = "STRICT"
    ECONOMIC = "ECONOMIC"


class LedgerComparisonStatus(StrEnum):
    EQUIVALENT = "EQUIVALENT"
    DIFFERENT = "DIFFERENT"
    INCOMPARABLE = "INCOMPARABLE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class LedgerComparisonRequest:
    left: ReplayEvidence
    right: ReplayEvidence
    mode: LedgerComparisonMode = LedgerComparisonMode.STRICT
    tolerance: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.left, ReplayEvidence) or not isinstance(self.right, ReplayEvidence):
            raise TypeError("ledger comparison requires ReplayEvidence on both sides")
        if not isinstance(self.mode, LedgerComparisonMode):
            raise TypeError("mode must be LedgerComparisonMode")
        if (
            type(self.tolerance) not in (int, float)
            or not math.isfinite(self.tolerance)
            or self.tolerance < 0
        ):
            raise ValueError("tolerance must be finite and non-negative")


@dataclass(frozen=True)
class LedgerDifference(Record):
    path: str
    reason: str


@dataclass(frozen=True)
class LedgerComparisonResult(Record):
    status: LedgerComparisonStatus
    mode: LedgerComparisonMode
    left_hash: str | None
    right_hash: str | None
    differences: tuple[LedgerDifference, ...]
    economic_sha256: str | None = None


_TABLES = ("decisions", "orders", "fills", "account_daily", "trades")
_OWNERS = {"decision_id": "decisions", "order_id": "orders", "fill_id": "fills"}


def _references(payload: dict) -> None:
    if any(not isinstance(row, Mapping) for table in _TABLES for row in payload[table]):
        raise ValueError("ledger tables must contain mapping records")
    sessions = tuple(date.fromisoformat(value) for value in payload["evaluation_sessions"])
    accounts = tuple(date.fromisoformat(row["date"][:10]) for row in payload["account_daily"])
    if not sessions or tuple(sorted(set(sessions))) != sessions or accounts != sessions:
        raise ValueError("account_daily: incomplete or invalid session coverage")
    owners = {}
    for field, table in _OWNERS.items():
        values = [row.get(field) for row in payload[table]]
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"{table}.{field}: missing identity")
        if len(values) != len(set(values)):
            raise ValueError(f"{table}.{field}: duplicate identity")
        owners[field] = set(values)
    orders = {row["order_id"]: row for row in payload["orders"]}
    cycles = set()
    for table in _TABLES:
        for row in payload[table]:
            for field, ids in owners.items():
                if field in row and row[field] is not None and row[field] not in ids:
                    raise ValueError(f"{table}.{field}: dangling reference")
            if table in ("orders", "fills") and row.get("decision_id") not in owners["decision_id"]:
                raise ValueError(f"{table}.decision_id: missing reference")
            cycle = row.get("cycle_id")
            if table in ("orders", "fills", "trades"):
                if not isinstance(cycle, str) or not cycle:
                    raise ValueError(f"{table}.cycle_id: missing reference")
            if table == "orders":
                cycles.add(cycle)
            if table == "fills":
                order = orders.get(row.get("order_id"))
                if order is None or any(
                    row.get(key) != order.get(key) for key in ("decision_id", "cycle_id")
                ):
                    raise ValueError("fills: order relationship differs")
            if table == "trades" and cycle not in cycles:
                raise ValueError("trades.cycle_id: dangling reference")


def _normalize(payload: dict) -> None:
    maps = {field: {} for field in (*_OWNERS, "cycle_id")}
    for table in _TABLES:
        for row in payload[table]:
            for field, mapping in maps.items():
                if field in row and row[field] is not None:
                    value = row[field]
                    if value not in mapping:
                        mapping[value] = f"{field}:{len(mapping)}"
                    row[field] = mapping[value]
    payload.pop("strategy_hash")


def _differences(left, right, path: str, tolerance: float, found: list) -> None:
    if len(found) >= 20:
        return
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            found.append(LedgerDifference(path, "FIELDS_DIFFER"))
        for key in sorted(set(left) & set(right)):
            _differences(left[key], right[key], f"{path}.{key}", tolerance, found)
    elif isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            found.append(LedgerDifference(path, "ROW_COUNT_DIFFERS"))
        for index, (a, b) in enumerate(zip(left, right)):
            _differences(a, b, f"{path}[{index}]", tolerance, found)
    elif type(left) in (int, float) and type(right) in (int, float):
        if not math.isfinite(left) or not math.isfinite(right) or abs(left - right) > tolerance:
            found.append(LedgerDifference(path, "VALUE_DIFFERS"))
    elif type(left) is not type(right) or left != right:
        found.append(LedgerDifference(path, "VALUE_DIFFERS"))


def compare_ledgers(request: LedgerComparisonRequest) -> LedgerComparisonResult:
    """Compare all evidence fields; ECONOMIC only renames IDs and omits strategy hash.

    Context mismatches are incomparable. Duplicate IDs and broken references are
    invalid even when identical on both sides. This comparison is not a replay audit.
    Differences are bounded to the first twenty paths; source evidence is untouched.
    """
    if not isinstance(request, LedgerComparisonRequest):
        raise TypeError("request must be LedgerComparisonRequest")
    same_evidence = request.left is request.right
    sides = (("left", request.left),) if same_evidence else (
        ("left", request.left), ("right", request.right)
    )
    hashes = []
    invalid = []
    shared_payload = None
    for side, evidence in sides:
        try:
            payload = evidence.to_dict()
            json.dumps(payload, allow_nan=False)
            if same_evidence:
                shared_payload = payload
                hash_payload = dict(payload)
                hash_payload.pop("content_hash")
                encoded = json.dumps(
                    hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
                hashes.append(sha256(encoded).hexdigest())
            else:
                hashes.append(hash_replay_evidence(evidence))
        except (TypeError, ValueError):
            hashes.append(None)
            invalid.append(LedgerDifference(side, "NON_JSON_OR_NONFINITE_EVIDENCE"))
    if same_evidence:
        hashes *= 2
        if invalid:
            invalid.append(LedgerDifference("right", invalid[0].reason))

    def result(status, differences):
        return LedgerComparisonResult(status, request.mode, *hashes, tuple(differences))

    if invalid:
        return result(LedgerComparisonStatus.INVALID, invalid)

    payloads = [shared_payload] if same_evidence else [
        request.left.to_dict(), request.right.to_dict()
    ]
    for (side, evidence), digest, payload in zip(sides, hashes, payloads):
        if evidence.content_hash and evidence.content_hash != digest:
            return result(
                LedgerComparisonStatus.INVALID, [LedgerDifference(side, "CONTENT_HASH_MISMATCH")]
            )
        try:
            _references(payload)
        except (ValueError, TypeError, KeyError) as exc:
            return result(LedgerComparisonStatus.INVALID, [LedgerDifference(side, str(exc))])
        payload.pop("content_hash")
    context = (
        "data_hash",
        "initial_cash",
        "evaluation_sessions",
        "execution_spec",
        "execution_daily",
        "execution_intraday",
    )
    mismatches = []
    if not same_evidence:
        for field in context:
            _differences(payloads[0][field], payloads[1][field], field, 0, mismatches)
    if mismatches:
        return result(LedgerComparisonStatus.INCOMPARABLE, mismatches)
    if request.mode is LedgerComparisonMode.ECONOMIC:
        for payload in payloads:
            _normalize(payload)
    differences = []
    if not same_evidence:
        _differences(*payloads, "replay", request.tolerance, differences)
    compared = result(
        LedgerComparisonStatus.DIFFERENT if differences else LedgerComparisonStatus.EQUIVALENT,
        differences,
    )
    if request.mode is LedgerComparisonMode.ECONOMIC and not differences and request.tolerance == 0:
        def canonical(value):
            if isinstance(value, Mapping):
                return ["object", [[key, canonical(value[key])] for key in sorted(value)]]
            if isinstance(value, (tuple, list)):
                return ["array", [canonical(item) for item in value]]
            if type(value) in (int, float):
                number = Decimal(str(value))
                text = format(number, "f")
                if "." in text:
                    text = text.rstrip("0").rstrip(".")
                return ["number", "0" if number == 0 else text]
            return [type(value).__name__, value]
        digest = sha256(json.dumps(canonical(payloads[0]), sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        compared = replace(compared, economic_sha256=digest)
    return compared
