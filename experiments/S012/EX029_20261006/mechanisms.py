"""Fixed causal catalyst hypotheses; no labels enter features or directions."""
import numpy as np
import pandas as pd

# id, primary horizon, causal parent, role, hypothesis
HYPOTHESES = (
    ("G01",20,"C_GOLD","机会环境","实际利率下降且黄金确认上涨，需求变化可能持续"),
    ("G02",20,"C_GOLD","机会环境","通胀补偿上升而实际利率未升，黄金上涨获得货币条件支持"),
    ("G03",5,"C_STRESS","机会","风险上升但黄金保持上涨，避险需求可能继续传导"),
    ("G04",5,"C_STRESS","竞争反证","风险上升且黄金下跌，现金压力可能压过避险需求"),
    ("G05",10,"C_GOLD5","机会环境","美元黄金上涨且人民币未贬值，收益更可能来自黄金自身"),
    ("G06",5,"C_FX","竞争解释","仅人民币贬值而美元黄金不涨，换算贡献可能短暂"),
    ("G07",10,"C_GOLD5","机会环境","美元金价与人民币贬值共同支持，人民币金价需求可能持续"),
    ("G08",10,"C_GOLD","机会","美元黄金长趋势向上中的短回调可能是需求未破坏的买入时点"),
    ("L01",3,"C_PEER_CHEAP","机会","共同黄金需求向上而目标落后同类ETF，价差可能修复"),
    ("L02",3,"C_SGE_CHEAP","机会","黄金需求向上且目标相对同日境内现货便宜，传导可能尚未完成"),
    ("L03",5,"C_FLOW","机会","份额增长但ETF尚未涨、全球黄金趋势正，可能存在未充分定价的配置需求"),
    ("L04",5,"C_FLOW","竞争解释","份额增长且ETF已经上涨，资金可能仅追随价格"),
    ("L05",5,"C_BASIS","机会环境","期货现货基差上升且全球黄金趋势正，可能反映需求增强"),
    ("L06",5,"C_FX","机会","汇率支持、全球黄金趋势正且ETF短回调，可能存在人民币收益修复"),
    ("M01",10,"C_ETF_MOM","确认","趋势信噪比高且短期惯性正可能提高上涨持续性；采用明确自定义公式"),
    ("M02",5,"C_ETF_MOM","确认","上涨环境下低ATR状态可能提高成交后的上涨质量"),
    ("M03",5,"C_ETF_MOM","竞争反证","上涨环境下高ATR状态可能伴随趋势衰竭"),
    ("M04",5,"C_ETF_MOM","竞争反证","价格创新高但成交量低于历史均值可能削弱上涨持续性"),
    ("M05",5,"C_STRESS","确认","风险上升且黄金历史上随风险上涨时，避险传导可能更清楚"),
)

def indexed(frame):
    x=frame.copy();x.attrs={}
    x["Date"]=pd.to_datetime(x["Date"])
    x=x.set_index("Date").sort_index()
    if not x.index.is_unique: raise ValueError("duplicate native source dates")
    return x

def align(native,index,name,lag_days=1,explicit=False,availability_calendar=None):
    x=native.copy();x.attrs={}
    if explicit:
        if "AvailableDate" not in x: raise ValueError("explicit availability required")
        x["AvailableDate"]=pd.to_datetime(x["AvailableDate"])
    elif availability_calendar is not None:
        # ETF shares T+1 means the next actual China trading session at 08:30.
        calendar=pd.DatetimeIndex(availability_calendar)
        pos=calendar.searchsorted(x.index,side="right")
        x["AvailableDate"]=[calendar[p]+pd.Timedelta(hours=8,minutes=30)
                            if p<len(calendar) else pd.NaT for p in pos]
    else:
        x["AvailableDate"]=x.index+pd.Timedelta(days=lag_days,hours=8,minutes=30)
    x=x.reset_index(names="SourceDate").dropna(subset=["AvailableDate"]).sort_values("AvailableDate")
    target=pd.DataFrame({"Date":index,"DecisionTime":index+pd.Timedelta(hours=17)})
    out=pd.merge_asof(target,x,left_on="DecisionTime",right_on="AvailableDate",
                      direction="backward",tolerance=pd.Timedelta(days=7)).set_index("Date")
    found=out.AvailableDate.notna()
    assert (out.loc[found,"AvailableDate"]<=out.loc[found,"DecisionTime"]).all()
    assert (out.loc[found,"SourceDate"]<out.index[found]).all()
    evidence=out[["SourceDate","AvailableDate","DecisionTime"]].add_prefix(name+"_")
    return out.drop(columns=["SourceDate","AvailableDate","DecisionTime"]),evidence

def build(frames):
    d=indexed(frames["daily"]);peer=indexed(frames["peer"]).reindex(d.index)
    index=d.index
    f=pd.DataFrame(index=index);audit=[]
    for h in (1,3,5,20):
        f[f"etf{h}"]=d.Close.pct_change(h,fill_method=None)
    f["vol20"]=f.etf1.rolling(20,min_periods=20).std()
    lr=np.log(d.Close).diff()
    f["trend_snr20"]=lr.rolling(20,min_periods=20).mean()/lr.rolling(20,min_periods=20).std()*np.sqrt(20)
    f["rho60"]=lr.rolling(60,min_periods=60).corr(lr.shift(1))
    tr=pd.concat([d.High-d.Low,(d.High-d.Close.shift(1)).abs(),(d.Low-d.Close.shift(1)).abs()],axis=1).max(axis=1)
    f["atr14"]=tr.rolling(14,min_periods=14).mean()/d.Close
    f["atr_low"]=f.atr14.rolling(126,min_periods=63).quantile(.25).shift(1)
    f["atr_high"]=f.atr14.rolling(126,min_periods=63).quantile(.75).shift(1)
    f["new_high20"]=d.Close/d.Close.rolling(20,min_periods=20).max().shift(1)-1
    f["volume_ratio"]=d.Volume/d.Volume.rolling(20,min_periods=20).mean().shift(1)
    for name in ("xau","fx"):
        x=indexed(frames[name])
        f0=pd.DataFrame({"level":x.BidClose,"AvailableDate":pd.to_datetime(x.AvailableDate)})
        for h in (1,5,20,60):
            f0[f"{name}{h}"]=x.BidClose.pct_change(h,fill_method=None)
        a,e=align(f0,index,name,explicit=True)
        for c in a:
            f[f"{name}_level" if c=="level" else c]=a[c]
        audit.append(e)
    # Simultaneous source-date legs; this is a conversion proxy, not a tradable NAV.
    gold=indexed(frames["xau"]);fx=indexed(frames["fx"])
    pair=gold[["BidClose","AvailableDate"]].join(fx[["BidClose","AvailableDate"]],lsuffix="_gold",rsuffix="_fx",how="inner")
    product=pair.BidClose_gold*pair.BidClose_fx
    p=pd.DataFrame({"rmb20":product.pct_change(20,fill_method=None),
        "AvailableDate":pair[["AvailableDate_gold","AvailableDate_fx"]].max(axis=1)})
    a,e=align(p,index,"paired",explicit=True);f["rmb20"]=a.rmb20;audit.append(e)
    real=indexed(frames["real_yield"]);nominal=indexed(frames["nominal_yield"])
    native=pd.DataFrame({"real":real.RealYield10YPercent,"nominal":nominal.NominalYield10YPercent}).dropna()
    native["breakeven"]=native.nominal-native.real
    native["real5"]=native.real.diff(5);native["be5"]=native.breakeven.diff(5)
    a,e=align(native,index,"yield");f["real5"]=a.real5;f["be5"]=a.be5;audit.append(e)
    stress=indexed(frames["vix"])
    a,e=align(pd.DataFrame({"vix5":stress.Close.diff(5)}),index,"vix")
    f["vix5"]=a.vix5;audit.append(e)
    native=gold[["BidClose","AvailableDate"]].join(stress[["Close"]],how="inner")
    native["gold_vix_corr60"]=native.BidClose.pct_change(fill_method=None).rolling(60,min_periods=60).corr(native.Close.diff())
    native["AvailableDate"]=pd.concat([pd.to_datetime(native.AvailableDate),
        pd.Series(native.index+pd.Timedelta(days=1,hours=8,minutes=30),index=native.index)],axis=1).max(axis=1)
    a,e=align(native[["gold_vix_corr60","AvailableDate"]],index,"vix_corr",explicit=True)
    f["gold_vix_corr60"]=a.gold_vix_corr60;audit.append(e)
    shares=indexed(frames["shares"])
    a,e=align(pd.DataFrame({"flow5":shares.TotalShare.pct_change(5,fill_method=None)}),
              index,"shares",availability_calendar=index)
    f["flow5"]=a.flow5;audit.append(e)
    # ETF ratios use same-close China legs. Spot ratio is additionally prior-day.
    ratio=d.Close/peer.Close
    base=ratio.rolling(60,min_periods=60).median().shift(1)
    f["peer_dev"]=ratio/base-1;f["peer5"]=peer.Close.pct_change(5,fill_method=None)
    sge=indexed(frames["sge"]);ratio=d.Close/sge.Close
    s=pd.DataFrame({"sge_dev":ratio/ratio.rolling(60,min_periods=60).median().shift(1)-1})
    a,e=align(s,index,"sge");f["sge_dev"]=a.sge_dev;audit.append(e)
    fut=frames["futures"].copy();fut.attrs={};fut["Date"]=pd.to_datetime(fut.Date)
    fut["maturity_days"]=(pd.to_datetime(fut.MaturityDate)-fut.Date).dt.days
    liquid=fut.loc[(fut.Volume>0)&(fut.maturity_days>=20)].sort_values(["Date","OpenInterest","Contract"])
    dom=liquid.groupby("Date").tail(1).set_index("Date")
    b=pd.DataFrame({"basis":dom.Settle/sge.Close-1})
    # A dominant-contract switch is not evidence of changing demand. Require
    # one contract throughout the six observations forming the five-day change.
    stable=pd.concat([dom.Contract.shift(j) for j in range(6)],axis=1).eq(dom.Contract,axis=0).all(axis=1)
    b["basis5"]=b.basis.diff(5).where(stable)
    a,e=align(b,index,"basis");f["basis5"]=a.basis5;audit.append(e)
    # All signs/definitions fixed from mechanisms; quantiles are trailing only.
    peer_low=f.peer_dev.rolling(126,min_periods=63).quantile(.25).shift(1)
    spot_low=f.sge_dev.rolling(126,min_periods=63).quantile(.25).shift(1)
    f["peer_low"]=peer_low;f["spot_low"]=spot_low
    expressions={
        "C_GOLD":(f.xau20>0,["xau20"]),
        "C_GOLD5":(f.xau5>0,["xau5"]),
        "C_FX":(f.fx5>0,["fx5"]),
        "C_STRESS":(f.vix5>0,["vix5"]),
        "C_FLOW":(f.flow5>0,["flow5"]),
        "C_BASIS":(f.basis5>0,["basis5"]),
        "C_PEER_CHEAP":(f.peer_dev<peer_low,["peer_dev","peer_low"]),
        "C_SGE_CHEAP":(f.sge_dev<spot_low,["sge_dev","spot_low"]),
        "C_ETF_MOM":(f.etf5>0,["etf5"]),
        "C_REAL":(f.real5<0,["real5"]),
        "C_BE":(f.be5>0,["be5"]),
        "G01":((f.real5<0)&(f.xau20>0),["real5","xau20"]),
        "G02":((f.be5>0)&(f.real5<=0)&(f.xau20>0),["be5","real5","xau20"]),
        "G03":((f.vix5>0)&(f.xau5>0),["vix5","xau5"]),
        "G04":((f.vix5>0)&(f.xau5<=0),["vix5","xau5"]),
        "G05":((f.xau5>0)&(f.fx5<=0),["xau5","fx5"]),
        "G06":((f.xau5<=0)&(f.fx5>0),["xau5","fx5"]),
        "G07":((f.xau5>0)&(f.fx5>0),["xau5","fx5"]),
        "G08":((f.xau20>0)&(f.xau5<=0)&(f.rmb20>0),["xau20","xau5","rmb20"]),
        "L01":((f.peer_dev<peer_low)&(f.peer5>0)&(f.etf1<=0),["peer_dev","peer_low","peer5","etf1"]),
        "L02":((f.sge_dev<spot_low)&(f.rmb20>0),["sge_dev","spot_low","rmb20"]),
        "L03":((f.flow5>0)&(f.etf5<=0)&(f.xau20>0),["flow5","etf5","xau20"]),
        "L04":((f.flow5>0)&(f.etf5>0)&(f.xau20>0),["flow5","etf5","xau20"]),
        "L05":((f.basis5>0)&(f.xau20>0),["basis5","xau20"]),
        "L06":((f.fx5>0)&(f.xau20>0)&(f.etf3<0),["fx5","xau20","etf3"]),
        "M01":((f.etf5>0)&(f.trend_snr20>1)&(f.rho60>0),["etf5","trend_snr20","rho60"]),
        "M02":((f.etf5>0)&(f.atr14<f.atr_low),["etf5","atr14","atr_low"]),
        "M03":((f.etf5>0)&(f.atr14>f.atr_high),["etf5","atr14","atr_high"]),
        "M04":((f.etf5>0)&(f.new_high20>0)&(f.volume_ratio<1),["etf5","new_high20","volume_ratio"]),
        "M05":((f.vix5>0)&(f.gold_vix_corr60>0)&(f.xau5>0),["vix5","gold_vix_corr60","xau5"]),
    }
    signals=pd.DataFrame(index=index);valids=pd.DataFrame(index=index)
    for name,(condition,required) in expressions.items():
        valid=f[required].notna().all(axis=1)
        valids[name]=valid;signals[name]=condition&valid
    return d,f,signals,valids,pd.concat(audit,axis=1)

def synthetic_frames():
    idx=pd.bdate_range("2020-06-05",periods=380);t=np.arange(len(idx));rng=np.random.default_rng(12029)
    close=5*np.exp(np.cumsum(rng.normal(.0004,.01,len(idx))))
    daily=pd.DataFrame({"Date":idx,"Open":close*.999,"Close":close,"Low":close*.98,
        "High":close*1.02,"Volume":10000.,"Amount":close*10000})
    xau=pd.DataFrame({"Date":idx,"BidClose":1800*np.exp(np.cumsum(rng.normal(.0005,.007,len(idx)))),
        "AvailableDate":idx+pd.Timedelta(days=2,hours=8)})
    fx=pd.DataFrame({"Date":idx,"BidClose":7*np.exp(np.cumsum(rng.normal(0,.001,len(idx)))),
        "AvailableDate":idx+pd.Timedelta(days=2,hours=8)})
    return {"daily":daily,"peer":daily.assign(Close=close*(1+np.sin(t/9)*.002)),
        "xau":xau,"fx":fx,"real_yield":pd.DataFrame({"Date":idx,"RealYield10YPercent":1+np.sin(t/11)*.4}),
        "nominal_yield":pd.DataFrame({"Date":idx,"NominalYield10YPercent":3+np.sin(t/13)*.5}),
        "vix":pd.DataFrame({"Date":idx,"Close":20+np.sin(t/5)*8}),
        "shares":pd.DataFrame({"Date":idx,"TotalShare":1e8+np.sin(t/19)*1e6}),
        "sge":daily.assign(Close=close*100),
        "futures":pd.DataFrame({"Date":idx,"Contract":"AU1","MaturityDate":idx+pd.Timedelta(days=90),
            "Settle":close*100*(1+np.sin(t/11)*.01),"Volume":1000.,"OpenInterest":10000.})}
