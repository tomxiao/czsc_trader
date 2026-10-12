"""Synthetic boundary checks for the newly authorised pooled-positive-year gate."""
from dataclasses import replace
from pathlib import Path
import json
from gates_v2 import AnnualFact,review


def run():
    good=(AnnualFact(2020,.20,.04,.10,.10,243,17),
          AnnualFact(2022,.001,.08,-.15,.25,242,0),
          AnnualFact(2026,.02,.03,.01,.12,181,12))
    r=review(net_cagr=.16,benchmark_cagr=.10,annual=good)
    assert r.positive_sessions==424 and r.positive_closed_cycles==29 and r.qualified
    assert r.all_year_frequency60<4 and r.positive_frequency60>4
    less=(replace(good[0],closed_cycles=16),good[1],good[2])
    assert not review(net_cagr=.16,benchmark_cagr=.1,annual=less).gates['positive_buyhold_year_frequency']
    assert not review(net_cagr=.16,benchmark_cagr=.1,annual=(good[0],replace(good[1],strategy_return=0.),good[2])).gates['negative_buyhold_year_profit']
    assert not review(net_cagr=.16,benchmark_cagr=.1,annual=(replace(good[0],strategy_drawdown=.1),good[1],good[2])).gates['annual_drawdown']
    neutral=replace(good[1],benchmark_return=0.,strategy_return=-.01)
    assert review(net_cagr=.16,benchmark_cagr=.1,annual=(good[0],neutral,good[2])).qualified
    exact=AnnualFact(2020,.2,.04,.1,.1,240,16)
    assert review(net_cagr=1.5*.1,benchmark_cagr=.1,annual=(exact,)).qualified
    rejected=0
    for action in (lambda:review(net_cagr=float('nan'),benchmark_cagr=.1,annual=good),
                   lambda:review(net_cagr=.15,benchmark_cagr=.1,annual=(good[1],)),
                   lambda:review(net_cagr=.15,benchmark_cagr=.1,annual=(good[0],good[0])),
                   lambda:replace(good[0],sessions=0),
                   lambda:replace(good[0],closed_cycles=-1)):
        try:
            action()
        except ValueError:
            rejected+=1
        else:
            raise AssertionError('Illegal gate input accepted')
    proof={'status':'PASS','real_inputs':0,'checks':6,'explicit_refusals':rejected,
           'positive_only_not_all_pool_frequency':'PASS','strict_yearly_dd_and_profit':'PASS','neutral_year_not_positive_or_negative':'PASS'}
    path=Path(__file__).with_suffix('.json')
    with path.open('x',encoding='utf-8') as stream:
        json.dump(proof,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(proof)


if __name__=='__main__':
    run()
