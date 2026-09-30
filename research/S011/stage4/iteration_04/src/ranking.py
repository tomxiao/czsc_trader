"""Strict grid-based dominance and evidence-aware lexicographic partial ranking."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
import math

@dataclass(frozen=True)
class Metric:
    name:str
    direction:str
    resolution:str
    origin:str='0'
    def __post_init__(self):
        if not self.name or self.direction not in ('maximize','minimize'):raise ValueError('metric identity/direction')
        if not isinstance(self.resolution,str) or not isinstance(self.origin,str):raise ValueError('explicit decimal strings required')
        s,o=Decimal(self.resolution),Decimal(self.origin)
        if not s.is_finite() or s<=0 or not o.is_finite():raise ValueError('finite positive grid required')
    def bin(self,value):
        if not valid(value):raise ValueError('finite numeric value required')
        return int(((Decimal(str(value))-Decimal(self.origin))/Decimal(self.resolution)).to_integral_value(rounding=ROUND_HALF_UP))

def valid(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def pareto(rows,metrics):
    if not metrics or len({r['config_id'] for r in rows})!=len(rows):raise ValueError('unique IDs and nonempty metric set required')
    vectors={};unranked={}
    for r in rows:
        missing=[m.name for m in metrics if not valid(r.get(m.name))]
        if missing:unranked[r['config_id']]=missing
        else:vectors[r['config_id']]=[m.bin(r[m.name])*(1 if m.direction=='maximize' else -1) for m in metrics]
    dominated={a:sorted(b for b in vectors if a!=b and all(y>=x for x,y in zip(vectors[a],vectors[b])) and any(y>x for x,y in zip(vectors[a],vectors[b]))) for a in vectors}
    remaining=set(vectors);layers=[]
    while remaining:
        front=sorted(a for a in remaining if not remaining.intersection(dominated[a]))
        if not front:raise ValueError('dominance cycle')
        layers.append({'layer':len(layers)+1,'config_ids':front});remaining-=set(front)
    return {'layers':layers,'dominated_by':dominated,'unranked':unranked,'comparison_vectors':vectors,'automatic_promotion':False}

def compare(a,b,metrics):
    prefix=[]
    for m in metrics:
        x,y=a.get(m.name),b.get(m.name)
        if not valid(x) or not valid(y):
            return {'relation':'INCOMPARABLE','decisive_metric':m.name,'winner':None,'equal_prefix':prefix,
                    'value_a':x if valid(x) else None,'value_b':y if valid(y) else None,'bin_a':None,'bin_b':None}
        u,v=m.bin(x),m.bin(y)
        if u!=v:
            wins=(u>v)==(m.direction=='maximize')
            return {'relation':'A_BEFORE_B' if wins else 'B_BEFORE_A','decisive_metric':m.name,
                'winner':a['config_id'] if wins else b['config_id'],'equal_prefix':prefix,
                'value_a':x,'value_b':y,'bin_a':u,'bin_b':v}
        prefix.append(m.name)
    return {'relation':'TIE','decisive_metric':None,'winner':None,'equal_prefix':prefix,'value_a':None,'value_b':None,'bin_a':None,'bin_b':None}

def order(rows,layers,metrics):
    if not metrics or len({m.name for m in metrics})!=len(metrics):raise ValueError('unique metric order required')
    lookup={r['config_id']:r for r in rows};out=[];pairs=[]
    if len(lookup)!=len(rows):raise ValueError('duplicate config ID')
    for layer in layers:
        ids=layer['config_ids'];edges={c:set() for c in ids};ties={c:set() for c in ids};unknown={c:set() for c in ids}
        for a,b in combinations(ids,2):
            result=compare(lookup[a],lookup[b],metrics);pairs.append({'layer':layer['layer'],'config_a':a,'config_b':b,**result})
            if result['winner']:
                winner=result['winner'];edges[winner].add(b if winner==a else a)
            elif result['relation']=='TIE':ties[a].add(b);ties[b].add(a)
            else:unknown[a].add(b);unknown[b].add(a)
        def descendants(cid):
            seen=set();stack=list(edges[cid])
            while stack:
                c=stack.pop()
                if c==cid:raise ValueError('partial-order cycle')
                if c not in seen:seen.add(c);stack.extend(edges[c])
            return seen
        after={c:descendants(c) for c in ids}
        for c in ids:
            before={b for b in ids if c in after[b]};lo=len(before)+1;hi=len(ids)-len(after[c])
            # Missing metrics are disclosed separately from an actually unresolved pair.
            exact=lo if lo==hi else (lo if ties[c] and not unknown[c] and hi-lo+1==len(ties[c])+1 else None)
            out.append({'config_id':c,'pareto_layer':layer['layer'],'recommendation_rank':exact,'rank_min':lo,'rank_max':hi,
                'comparison_status':'PARTIAL_ORDER' if unknown[c] else ('TIED' if ties[c] else 'ORDERED'),
                'missing_metrics':[m.name for m in metrics if not valid(lookup[c].get(m.name))],
                'incomparable_with':sorted(unknown[c]),'tied_with':sorted(ties[c]),
                'strictly_before':sorted(after[c]),'strictly_after':sorted(before)})
    return out,pairs
