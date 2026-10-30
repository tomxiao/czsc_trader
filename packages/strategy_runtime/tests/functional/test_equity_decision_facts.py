"""Exact explanation semantics with bounded immutable fact-basis reuse."""
from dataclasses import FrozenInstanceError
import pickle

import pytest

from strategy_runtime import EquityDecision
from strategy_runtime.equity_definition import _cached_fact_basis
from strategy_runtime.signal_explanation import SignalBasisSnapshot, SignalExplanationSnapshot


def original(target, reason, *, facts, next_watch):
    """The public construction contract, independent of the reuse helper."""
    if type(facts) is not dict or not facts:
        raise ValueError('decision explanations require condition/parameter facts')
    return EquityDecision(target, reason, SignalExplanationSnapshot('target', 'long' if target else 'flat', reason,
        tuple(SignalBasisSnapshot(key, str(value)) for key, value in facts.items()), next_watch, reason))


def test_exact_text_order_full_snapshot_and_immutable_reuse():
    facts = {'later': '  保留原文\n', 'first': -0.0, 'boolean': True, 'missing': None,
             'mapping': {'nested': [1, 2]}}
    first = EquityDecision.from_facts(1, 'reason', facts=facts, next_watch='next')
    second = EquityDecision.from_facts(1, 'reason', facts=facts, next_watch='next')
    assert first == second == original(1, 'reason', facts=facts, next_watch='next')
    assert first.explanation.to_dict() == original(1, 'reason', facts=facts, next_watch='next').explanation.to_dict()
    assert [item.key for item in first.explanation.basis] == list(facts)
    assert first.explanation.basis[0].text == '  保留原文\n'
    assert first is not second and first.explanation is not second.explanation
    assert all(a is b for a, b in zip(first.explanation.basis, second.explanation.basis, strict=True))
    with pytest.raises(FrozenInstanceError):
        first.explanation.basis[0].text = 'changed'
    with pytest.raises(FrozenInstanceError):
        first.explanation.basis[0].key = 'changed'
    exported = first.explanation.to_dict()
    exported['basis'][0]['text'] = 'changed'
    assert second.explanation.basis[0].text == '  保留原文\n'
    assert pickle.loads(pickle.dumps(first)) == first


def test_distinct_strings_and_numeric_spellings_never_share_different_facts():
    texts = ['0', '-0', '0.0', '-0.0', '1', '1.0', ' True', 'True', 'é', 'e\u0301', '值', '值\n']
    values = [EquityDecision.from_facts(0, 'reason', facts={'value': text}, next_watch='next')
              .explanation.basis[0] for text in texts]
    assert [value.text for value in values] == texts
    assert len({id(value) for value in values}) == len(texts)
    different_key = EquityDecision.from_facts(0, 'reason', facts={'other': texts[0]}, next_watch='next').explanation.basis[0]
    assert different_key is not values[0]


@pytest.mark.parametrize('changes', [
    {'target': True}, {'target': 2}, {'reason': ''}, {'reason': None}, {'next_watch': ''},
    {'facts': {}}, {'facts': [('valid', 1)]}, {'facts': {'Invalid': 1}},
    {'facts': {1: 'text'}}, {'facts': {'valid': ''}}, {'facts': {'valid': ' \n'}},
])
def test_invalid_inputs_keep_original_exception_type_message_and_order(changes):
    args = {'target': 1, 'reason': 'reason', 'facts': {'valid': True}, 'next_watch': 'next'} | changes
    with pytest.raises(Exception) as expected:
        original(**args)
    for _ in range(2):
        with pytest.raises(type(expected.value)) as observed:
            EquityDecision.from_facts(**args)
        assert str(observed.value) == str(expected.value)


def test_string_subclasses_preserve_identity_and_do_not_add_hash_or_equality_calls():
    class Key(str):
        hashes = 0

        def __hash__(self):
            self.hashes += 1
            return super().__hash__()

        def __eq__(self, other):
            raise AssertionError('unexpected key comparison')

    class Text(str):
        __hash__ = None

        def __str__(self):
            return self

    key, text = Key('valid'), Text('text')
    facts = {key: text}
    for factory in (original, EquityDecision.from_facts, EquityDecision.from_facts):
        before = key.hashes
        item = factory(1, 'reason', facts=facts, next_watch='next').explanation.basis[0]
        assert key.hashes == before + 1  # Existing unique-key validation only.
        assert item.key is key and item.text is text
    for factory in (original, EquityDecision.from_facts):
        item = factory(1, 'reason', facts={'valid': text}, next_watch='next').explanation.basis[0]
        assert item.text is text  # Unhashable str subclass must not enter the cache.


def test_fact_values_are_converted_on_every_call_even_when_text_is_reused():
    class Value:
        calls = 0

        def __str__(self):
            self.calls += 1
            return 'same'

    value = Value()
    first = EquityDecision.from_facts(0, 'reason', facts={'value': value}, next_watch='next')
    second = EquityDecision.from_facts(0, 'reason', facts={'value': value}, next_watch='next')
    assert value.calls == 2
    assert first.explanation.basis[0] is second.explanation.basis[0]


def test_fact_basis_cache_is_bounded_and_eviction_preserves_results():
    _cached_fact_basis.cache_clear()
    limit = _cached_fact_basis.cache_info().maxsize
    assert 0 < limit <= 4096
    for number in range(limit + 1):
        EquityDecision.from_facts(0, 'reason', facts={'value': str(number)}, next_watch='next')
    assert _cached_fact_basis.cache_info().currsize == limit
    assert EquityDecision.from_facts(0, 'reason', facts={'value': '0'}, next_watch='next') == original(
        0, 'reason', facts={'value': '0'}, next_watch='next')
    _cached_fact_basis.cache_clear()
