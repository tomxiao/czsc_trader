"""Exact explanation semantics with bounded immutable fact-basis reuse."""



from strategy_runtime import EquityDecision
from strategy_runtime.equity_definition import _cached_fact_basis
from strategy_runtime.signal_explanation import SignalBasisSnapshot, SignalExplanationSnapshot


def original(target, reason, *, facts, next_watch):
    """The public construction contract, independent of the reuse helper."""
    if type(facts) is not dict or not facts:
        raise ValueError("decision explanations require condition/parameter facts")
    return EquityDecision(
        target,
        reason,
        SignalExplanationSnapshot(
            "target",
            "long" if target else "flat",
            reason,
            tuple(SignalBasisSnapshot(key, str(value)) for key, value in facts.items()),
            next_watch,
            reason,
        ),
    )


def test_SRT_26_C01_distinct_strings_and_numeric_spellings_never_share_different_facts():
    texts = ["0", "-0", "0.0", "-0.0", "1", "1.0", " True", "True", "é", "e\u0301", "值", "值\n"]
    values = [
        EquityDecision.from_facts(
            0, "reason", facts={"value": text}, next_watch="next"
        ).explanation.basis[0]
        for text in texts
    ]
    assert [value.text for value in values] == texts
    assert len({id(value) for value in values}) == len(texts)
    different_key = EquityDecision.from_facts(
        0, "reason", facts={"other": texts[0]}, next_watch="next"
    ).explanation.basis[0]
    assert different_key is not values[0]


def test_SRT_26_C02_fact_basis_cache_is_bounded_and_eviction_preserves_results():
    _cached_fact_basis.cache_clear()
    limit = _cached_fact_basis.cache_info().maxsize
    assert 0 < limit <= 4096
    for number in range(limit + 1):
        EquityDecision.from_facts(0, "reason", facts={"value": str(number)}, next_watch="next")
    assert _cached_fact_basis.cache_info().currsize == limit
    assert EquityDecision.from_facts(
        0, "reason", facts={"value": "0"}, next_watch="next"
    ) == original(0, "reason", facts={"value": "0"}, next_watch="next")
    _cached_fact_basis.cache_clear()
