"""EC plan evidence preserves JSON facts without encoding and parsing each tick."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

import pytest

from execution_channels.historical.portfolio import _serial


def test_plan_facts_preserve_scalar_types_and_independent_nested_values():
    class Side(StrEnum):
        BUY = 'BUY'

    @dataclass(frozen=True)
    class Intent:
        side: Side
        quantity: int
        limit: Decimal
        at: datetime
        facts: object

    source = Intent(Side.BUY, 10, Decimal('1.20'), datetime(2026, 1, 1, tzinfo=timezone.utc),
                    MappingProxyType({'enabled': True, 'nested': (1., None)}))
    result = _serial(source)
    assert result == {'side': 'BUY', 'quantity': 10, 'limit': '1.20',
                      'at': '2026-01-01T00:00:00+00:00', 'facts': {'enabled': True, 'nested': [1., None]}}
    assert type(result['side']) is str and type(result['quantity']) is int
    result['facts']['nested'][0] = 99
    assert _serial(source)['facts']['nested'][0] == 1.


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), -float('inf')])
def test_plan_facts_reject_nonfinite_numbers(invalid):
    with pytest.raises(ValueError, match='finite'):
        _serial({'value': invalid})


def test_plan_facts_reject_unsupported_objects():
    with pytest.raises(TypeError, match='unsupported'):
        _serial({'value': object()})
