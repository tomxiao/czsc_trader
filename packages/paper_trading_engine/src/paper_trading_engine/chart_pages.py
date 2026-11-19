"""Bound chart documents by session while retaining access to the full history."""

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from hashlib import sha256
import json


def encode_context(context: Mapping) -> str:
    return json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=str)


def history_pages(context: dict, fingerprint: str, *, input_limit: int) -> list[tuple[str, dict]]:
    encoded = encode_context(context)
    if len(encoded.encode("utf-8")) <= input_limit:
        return [(fingerprint, context)]

    decisions = context["execution"]["decisions"]
    observation_start = min((row["decision_date"] for row in decisions
                             if row["status"] != "SUPERSEDED"), default=None)
    observations = {row["decision_id"]: row for row in context["observations"]}
    groups = {}
    for kind, rows, key in (
        ("decisions", decisions, "decision_date"),
        ("fills", context["execution"]["fills"], "session"),
        ("snapshots", context["execution"]["snapshots"], "session"),
        ("bars", context["market_data"]["bars"], "date"),
    ):
        ordered = sorted(rows, key=lambda row: row[key])
        groups[kind] = ([row[key] for row in ordered], ordered)
    dates = sorted({day for keys, _ in groups.values() for day in keys})
    if not dates:
        raise ValueError("chart metadata exceeds the per-document input limit")

    def select(kind, start, end, *, preceding=0):
        keys, rows = groups[kind]
        left, right = bisect_left(keys, start), bisect_right(keys, end)
        return rows[max(0, left - preceding):right]

    def document(start, end):
        selected = select("decisions", start, end)
        bars = select("bars", start, end)
        return {
            **context,
            "window": {
                **context["window"],
                "forward_observation_start": min((row["signal_date"] for row in selected), default=None),
                "account_forward_observation_start": observation_start,
            },
            "market_data": {**context["market_data"], "bars": bars,
                            "as_of": bars[-1]["date"] if bars else end},
            "observations": [observations[row["decision_id"]] for row in selected
                             if row["decision_id"] in observations],
            "execution": {
                "decisions": selected,
                "fills": select("fills", start, end),
                "snapshots": select("snapshots", start, end, preceding=1),
            },
        }

    def split(left, right, budget):
        page = document(dates[left], dates[right])
        if len(encode_context(page).encode("utf-8")) <= budget:
            return [(dates[left], dates[right], page)]
        if left == right:
            raise ValueError(f"chart session {dates[left]} exceeds the per-document input limit")
        middle = (left + right) // 2
        return split(left, middle, budget) + split(middle + 1, right, budget)

    budget = input_limit
    while True:
        parts = split(0, len(dates) - 1, budget)
        pages = []
        for index, (start, end, _) in enumerate(parts):
            identity = fingerprint if index == len(parts) - 1 else sha256(
                f"{fingerprint}:{index}".encode()).hexdigest()
            pages.append({"start": start, "end": end, "fingerprint": identity})
        result, excess = [], 0
        for index, (_, _, page) in enumerate(parts):
            page["window"].update(history_pages=pages, history_page=index)
            excess = max(excess, len(encode_context(page).encode("utf-8")) - input_limit)
            result.append((pages[index]["fingerprint"], page))
        if excess <= 0:
            return result
        budget -= excess
        if budget <= 0:
            raise ValueError("chart history index exceeds the per-document input limit")
