"""User-authorised S013 v2 economics, separate from unchanged SE full-pool diagnostics."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class AnnualFact:
    year: int
    strategy_return: float
    strategy_drawdown: float
    benchmark_return: float
    benchmark_drawdown: float
    sessions: int
    closed_cycles: int

    def __post_init__(self):
        if not all(isfinite(x) for x in (self.strategy_return,self.strategy_drawdown,self.benchmark_return,self.benchmark_drawdown)):
            raise ValueError('Finite realised annual facts required')
        if type(self.sessions) is not int or type(self.closed_cycles) is not int or self.sessions<=0 or self.closed_cycles<0:
            raise ValueError('Actual positive sessions and nonnegative closed cycles')
        if not 0<=self.strategy_drawdown<=1 or not 0<=self.benchmark_drawdown<=1:
            raise ValueError('Drawdowns are magnitudes in [0,1]')


@dataclass(frozen=True)
class GateReview:
    gates: dict
    positive_years: tuple[int,...]
    positive_sessions: int
    positive_closed_cycles: int
    positive_frequency60: float
    all_year_frequency60: float

    @property
    def qualified(self):
        return all(self.gates.values())


def review(*, net_cagr: float, benchmark_cagr: float, annual: tuple[AnnualFact,...]) -> GateReview:
    if not annual or not all(isinstance(x,AnnualFact) for x in annual) or len({x.year for x in annual})!=len(annual):
        raise ValueError('Unique actual annual records required')
    if not isfinite(net_cagr) or not isfinite(benchmark_cagr):
        raise ValueError('Finite actual net CAGR and benchmark required')
    positive=tuple(x for x in annual if x.benchmark_return>0)
    if not positive:
        raise ValueError('This authorised development pool must contain positive benchmark years; do not mark missing frequency PASS')
    days=sum(x.sessions for x in positive)
    closed=sum(x.closed_cycles for x in positive)
    gates={'return':net_cagr>=1.5*benchmark_cagr if benchmark_cagr>0 else net_cagr>0,
           'annual_drawdown':all(x.strategy_drawdown<x.benchmark_drawdown for x in annual),
           'positive_buyhold_year_frequency':15*closed>=days,
           'negative_buyhold_year_profit':all(x.strategy_return>0 for x in annual if x.benchmark_return<0)}
    return GateReview(gates,tuple(x.year for x in positive),days,closed,60*closed/days,
                      60*sum(x.closed_cycles for x in annual)/sum(x.sessions for x in annual))


def from_economics(facts: dict) -> GateReview:
    annual=tuple(AnnualFact(int(y),float(v['return']),float(v['drawdown']),
                 float(facts['benchmark_annual'][y]['return']),float(facts['benchmark_annual'][y]['drawdown']),
                 v['sessions'],v['closed_cycles']) for y,v in sorted(facts['annual'].items()))
    return review(net_cagr=facts['net_cagr'],benchmark_cagr=facts['benchmark_cagr'],annual=annual)
