"""Order sizing for frozen binary equity targets, independent of strategy code."""
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_FLOOR
import math

from ..contracts import DecisionPoint, EquityPortfolio, EquityPlan
from ..policy import ResearchExecutionSpec, _positive
from ..identity import equity_hash


@dataclass(frozen=True, slots=True)
class FrozenEquityIntent:
    point: DecisionPoint
    target: float
    reference_price: float
    explanation: dict | None
    suppressed: bool = False

    def __post_init__(self):
        if (type(self.point) is not DecisionPoint or type(self.target) not in (float,int)
                or self.target not in (0,1)):
            raise ValueError('frozen equity intent requires a binary target and typed point')
        _positive(self.reference_price, 'reference')
        if self.explanation is not None and type(self.explanation) is not dict:
            raise TypeError('frozen equity explanation requires a record')
        if type(self.suppressed) is not bool:
            raise TypeError('frozen equity suppression requires a boolean')


def plan_frozen_equity(intent: FrozenEquityIntent, portfolio: EquityPortfolio,
                       specification: ResearchExecutionSpec, *, owner: str,
                       implementation: str, fee_rate: float) -> EquityPlan:
    if (type(intent) is not FrozenEquityIntent or type(portfolio) is not EquityPortfolio
            or type(specification) is not ResearchExecutionSpec):
        raise TypeError('frozen equity planning requires channel-owned contracts')
    if type(fee_rate) not in (int,float) or not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
        raise ValueError('invalid fee rate')
    if any(type(value) is not str or not value for value in (owner, implementation)):
        raise ValueError('frozen equity planning requires owner and implementation identities')
    point, target, reference = intent.point, intent.target, intent.reference_price
    explanation = intent.explanation
    if intent.suppressed:
        target = float(portfolio.quantity > 0)
        payload = {'candidate':owner,'implementation':implementation,
            'specification':specification.fingerprint,'point':asdict(point),
            'revision':portfolio.revision,'reference':reference,'target':target,
            'signal_status':'SUPPRESSED_UNOBSERVED_BAR'}
        return EquityPlan(equity_hash(payload), point, target, 0, 'WAIT', None,
            portfolio.revision, reference, specification.fingerprint,
            signal_status='SUPPRESSED_UNOBSERVED_BAR')
    side, quantity, limit = 'HOLD', 0, None
    if target == 1 and portfolio.quantity == 0:
        tick = Decimal(str(specification.price_tick))
        limit = float((Decimal(str(reference)) * (1 + Decimal(str(specification.buy_premium)))
            / tick).to_integral_value(rounding=ROUND_FLOOR) * tick)
        _positive(limit, 'limit')
        step = specification.quantity_step
        quantity = int(Decimal(str(portfolio.cash)) / (Decimal(str(limit)) * (1 + Decimal(str(fee_rate))) * step)) * step
        side = 'BUY' if quantity else 'WAIT'
    elif target == 0 and portfolio.quantity:
        side, quantity = 'SELL', portfolio.quantity
    payload = {'candidate':owner,'implementation':implementation,
        'specification':specification.fingerprint,'point':asdict(point),'target':target,
        'quantity':quantity,'side':side,'limit':limit,'revision':portfolio.revision,
        'reference':reference,'fee_rate':fee_rate}
    if explanation is not None:
        payload['explanation'] = explanation
    return EquityPlan(equity_hash(payload), point, float(target), quantity, side, limit,
        portfolio.revision, reference, specification.fingerprint, explanation)
