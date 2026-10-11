"""Generate self-contained scalar EX085 audit using prior independent primitives."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.tmp/s013-recent-payoff-state'
a = (ROOT/'research/S013/experiments/EX084_20261012/src/audit.py').read_text('utf-8')
k = (WORK/'kernel.py').read_text('utf-8')
start = a.index('MODELS = ')
end = a.index('\n\n\ndef mean')
ks = k.index('MODELS = ')
ke = k.index('\n\n\ndef validate')
a = a[:start]+k[ks:ke]+a[end:]

body = '''def ridge(train, target, test):
    n, d = len(train), len(train[0])
    mx, my = [mean([r[j] for r in train]) for j in range(d)], mean(target)
    z = [[r[j]-mx[j] for j in range(d)] for r in train]
    matrix = [[fsum(z[i][a]*z[i][b] for i in range(n))+(10 if a==b else 0) for b in range(d)] for a in range(d)]
    right = [fsum(z[i][j]*(float(target[i])-my) for i in range(n)) for j in range(d)]
    slopes = solve(matrix,right)
    intercept = my-fsum(a*b for a,b in zip(mx,slopes))
    return [intercept+fsum(a*b for a,b in zip(row,slopes)) for row in test],[intercept,*slopes]


def states(axis,y,ends):
    rows,traces=[],[]
    for date in axis:
        eligible=[i for i in range(len(axis)) if np.isfinite(y[i]) and pd.notna(ends.iloc[i]) and ends.iloc[i]<=date]
        window=eligible[-20:] if len(eligible)>=20 else []
        rows.append([sum(y[i]>0 for i in window)/20,mean(y[window])] if window else [np.nan,np.nan])
        traces.append({'signal_date':date.isoformat(),'eligible_mature':len(eligible),'available':len(window)==20,
                       'positions':window,'max_maturity':max(ends.iloc[i] for i in window).isoformat() if window else None})
    return pd.DataFrame(rows,index=axis,columns=('mature_h4_win_fraction20','mature_h4_mean_net20')),traces


def forecasts(features,labels):
    axis,y=features.index,labels.return_4.to_numpy(float)
    ends=pd.to_datetime(labels.label_end_return_4)
    state,traces=states(axis,y,ends)
    x=np.column_stack((features.to_numpy(float),state.to_numpy(float)))
    complete=[all(np.isfinite(v) for v in row) for row in x]
    nets=pd.DataFrame(np.nan,index=axis,columns=MODELS)
    probs=pd.DataFrame(np.nan,index=axis,columns=PROBABILITIES)
    years={}
    for year in sorted(set(t.year for t in axis if t.year>=2021)):
        first=next(t for t in axis if t.year==year)
        tr=[i for i,t in enumerate(axis) if complete[i] and np.isfinite(y[i]) and 2020<=t.year<year and ends.iloc[i]<first]
        te=[i for i,t in enumerate(axis) if complete[i] and t.year==year]
        wins=[i for i in tr if y[i]>0];losses=[i for i in tr if y[i]<=0]
        available=len(tr)>=40 and len(wins)>=20 and len(losses)>=20
        row={'first_signal':first.isoformat(),'train_n':len(tr),'win_n':len(wins),'nonpositive_n':len(losses),
             'max_maturity':max(ends.iloc[i] for i in tr).isoformat() if tr else None,'train_dates':[axis[i].isoformat() for i in tr],
             'feature_test_n':len(te),'available':available,'future_test_count_gate':False,'payoffs':None,
             'return_models':{},'probability_models':{}}
        if available:
            fraction,gain,negative=len(wins)/len(tr),mean(y[wins]),mean(y[losses])
            row['payoffs']={'win_fraction':fraction,'mean_positive':gain,'mean_nonpositive':negative,
                            'break_even_probability':-negative/(gain-negative),'unconditional_net_mean':mean(y[tr])}
            nets.iloc[te,0]=mean(y[tr]);probs.iloc[te,0]=fraction
            rt=[cdf(x[tr,j],x[tr,j]) for j in range(16)]
            rv=[cdf(x[tr,j],x[te,j]) for j in range(16)]
            for dim,net_name,prob_name,payoff_name in ((14,MODELS[1],PROBABILITIES[1],MODELS[3]),(16,MODELS[2],PROBABILITIES[2],MODELS[4])):
                tx=[[r[i] for r in rt[:dim]] for i in range(len(tr))]
                vx=[[r[i] for r in rv[:dim]] for i in range(len(te))]
                prediction,coef=ridge(tx,y[tr],vx)
                p,proof=fit(tx,[int(y[i]>0) for i in tr],vx)
                nets.iloc[te,nets.columns.get_loc(net_name)]=prediction
                probs.iloc[te,probs.columns.get_loc(prob_name)]=p
                nets.iloc[te,nets.columns.get_loc(payoff_name)]=[v*gain+(1-v)*negative for v in p]
                row['return_models'][net_name]=coef;row['probability_models'][prob_name]=proof
        years[str(year)]=row
    return state,traces,probs,nets,years


'''
s,e=a.index('def forecasts('),a.index('def compare(')
a=a[:s]+body+a[e:]
s,e=a.index('def quantities('),a.index('def verify(')
body='''def quantities(y,p,nets,ids):
    ix=[int(i) for i in ids if np.isfinite(y[int(i)]) and np.isfinite(p[int(i)]).all() and np.isfinite(nets[int(i)]).all()]
    if len(ix)<20:
        return dict.fromkeys(QUANTITIES)
    binary=[int(y[i]>0) for i in ix]
    brier=[mean([(p[i,j]-b)**2 for i,b in zip(ix,binary)]) for j in range(3)]
    losses=[mean([-b*log(p[i,j])-(1-b)*log1p(-p[i,j]) for i,b in zip(ix,binary)]) for j in range(3)]
    mse=[mean([(nets[i,j]-y[i])**2 for i in ix]) for j in range(5)]
    avg=[]
    for j in range(5):
        v=[y[i] for i in ix if nets[i,j]>0]
        avg.append(mean(v) if len(v)>=20 else None)
    out={key:float(1-values[a]/values[b]) if values[b]>0 else None for key,(values,a,b) in zip(QUANTITIES[:4],((brier,2,1),(losses,2,1),(mse,2,1),(mse,4,3)))}
    out.update({QUANTITIES[4]:avg[2],QUANTITIES[5]:avg[4]})
    for key,new,old in ((QUANTITIES[6],2,1),(QUANTITIES[7],4,3)):
        out[key]=avg[new]-avg[old] if avg[new] is not None and avg[old] is not None else None
    out[QUANTITIES[8]]=float(1-brier[2]/brier[0]) if brier[0]>0 else None
    out[QUANTITIES[9]]=float(1-losses[2]/losses[0]) if losses[0]>0 else None
    return out


'''
a=a[:s]+body+a[e:]
a=a.replace('def verify(features, labels, prior, reported_probs, reported_nets, report, clock):\n    probs, nets, fits = forecasts(features, labels, prior)',
'''def verify(features, labels, reported_states, reported_probs, reported_nets, report, clock):
    state, traces, probs, nets, fits = forecasts(features, labels)
    np.testing.assert_allclose(reported_states,state,atol=3e-12,rtol=2e-9,equal_nan=True)
    compare(report['state_traces'],traces,'state_traces')''')
a=a.replace("'new_annual_models': 2 * sum", "'new_annual_models': 4 * sum")
a=a.replace("'payoff_decomposition': 'VERIFIED',", "'payoff_decomposition': 'VERIFIED', 'state_cells': 2*len(y), 'matched_training': True,")
a=a.replace('Scalar Newton logistic audit; independently reconstructed payoffs and utility', 'Scalar mature-window, matched ridge/Newton and economic utility audit')
# Normalize generated multi-statement lines before freezing; math unchanged.
lines=[]
for line in a.splitlines():
    if ';' in line and not line.lstrip().startswith('#'):
        indent=line[:len(line)-len(line.lstrip())]
        lines.extend(indent+part.strip() for part in line.strip().split(';'))
    else:
        lines.append(line)
(WORK/'audit.py').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
print('EX085 scalar audit written; no real inputs or experiment allocation')
