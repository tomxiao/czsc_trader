"""Stage-two first-principles hypothesis census; existing bound resources only."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research_experiment import (
    ResearchExperiment,ExperimentDefinition,ExperimentMode,ExperimentDataScope,
    ExperimentCapabilities,ExperimentProtocol,ExperimentStage,ExperimentResult,
    ExperimentOutcome,ExperimentDependency,ExperimentPrecheckResult,
    ExperimentPreflightCheck,ExperimentPreflightStatus,ExperimentCapability)
from .mechanisms import build,synthetic_frames,HYPOTHESES
from .diagnostics import run,labels,anchors,row

EID="EX029_20261006"
INPUTS={
    "daily":("EX015_20261005","data/daily.parquet"),
    "peer":("EX015_20261005","data/peer.parquet"),
    "xau":("EX010_20261004","data/xau.parquet"),
    "fx":("EX010_20261004","data/fx.parquet"),
    **{k:("EX004_20261004",f"data/{k}.parquet") for k in
       ("real_yield","nominal_yield","shares","vix","sge","futures")},
}

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,EID,"S012",ExperimentMode.FORMAL,
            "催化变化、黄金自身确认和境内传导残差是否提供成交后的增量收益信息？",
            "慢变货币条件影响持续需求，短变相对价格与未追涨份额可能影响传导；价格和风险状态须竞争解释。",
            ("同费用对照、价格及汇率控制后无增量，或收益只集中在个别已见年度。",
             "发布延迟消除优势；份额只是追涨；比值同步偏差或换月主导；微观状态不提供独立信息。"),
            date(2026,9,30),12029,
            ("fx.fxcm_daily","fx.usdcnh_daily","etf.unadjusted_daily","macro.us_real_yield_daily",
             "macro.us_nominal_yield_daily","etf.share_size","index.vix_daily","metal.sge_gold_daily",
             "futures.shfe_gold.daily"),
            ExperimentProtocol(ExperimentStage.MECHANISM_DISCOVERY,
                ("用户授权回到阶段二重建收益假设；阶段三空达标集合为已见反证，不构建新账户。",),
                ("18固定收益/确认/竞争假设与11基本对照；宏观、避险、配置资金和执行状态优先级。",),
                ("先冻结方向、主期限、父对照和统计协议，再读本轮收益；完整保留反例。",),
                ("1/3/5/10/20日T+1开盘到开盘净事件收益；18各自固定主期限，隔夜/日内贡献。",),
                ("源时间显式对齐T17:00；FXCM源日后2自然日08:00政策假设保持。",
                 "5来源变化不被水平替代；本地ETF份额不是全球黄金ETF流入，USD/CNH不是DXY。",
                 "同费父对照、年度价格/波动/黄金/汇率状态匹配、OLS、年度与非重叠诊断。",
                 "18主假设年内循环移位399次/BH和20交易日期块999次区间；其余敏感性仅描述。",
                 "成本各侧10/20bp，延迟0/2日；全部历史已见开发池，无质量未来掩码，无新经济硬门。",
                 "未具备DXY、GVZ、全球ETF、COT及央行逐时可得序列，相关假设明确未检验。"),
                predecessor_experiment_ids=("EX004_20261004","EX010_20261004","EX015_20261005","EX028_20261006")),
            ExperimentDataScope.DEVELOPMENT,subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ("numpy","pandas")),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=False))

    def synthetic_precheck(self):
        frames=synthetic_frames();d,f,s,v,a=build(frames)
        index=d.index;cut=index[299]
        prefix={k:x.loc[pd.to_datetime(x.Date)<=cut].copy() for k,x in frames.items()}
        dd,ff,ss,vv,aa=build(prefix)
        for x,y in ((d,dd),(f,ff),(s,ss),(v,vv),(a,aa)):
            pd.testing.assert_frame_equal(x.loc[:cut],y)
        changed={k:x.copy() for k,x in frames.items()}
        changed["xau"].loc[300:,"BidClose"]*=10
        _,changed_f,changed_s,_,_=build(changed)
        pd.testing.assert_frame_equal(f.loc[:cut],changed_f.loc[:cut])
        pd.testing.assert_frame_equal(s.loc[:cut],changed_s.loc[:cut])
        absent={k:x.copy() for k,x in frames.items()}
        absent["xau"]["BidClose"]=np.nan
        _,_,_,invalid,_=build(absent)
        assert not invalid["G01"].any()
        p=labels(d,5,0,.001)
        expected=d.Open.iloc[6]/d.Open.iloc[1]*.999/1.001-1
        assert abs(p.net.iloc[0]-expected)<1e-12
        assert p.net.iloc[-6:].isna().all()
        assert np.array_equal(anchors(np.array([1,1,1,1,1],dtype=bool),3),[0,3])
        # An all-days signal must have zero same-fee/within-cell residual increment.
        alltrue=pd.Series(True,index=index)
        r,_,_=row(p,f,alltrue,alltrue,alltrue,5,0,.001,"synthetic_all")
        assert abs(r["net_mean"]-r["unconditional_same_fee"])<1e-12
        assert abs(r["matched_increment"])<1e-12
        checks=tuple(ExperimentPreflightCheck(code,ExperimentPreflightStatus.PASS,text) for code,text in (
            ("CAUSAL_PREFIX","全部特征、信号、有效位及时间证据截断与未来金价扰动不改过去"),
            ("MISSING_BOUNDARY","缺黄金输入不产生宏观信号；日期、明确可得时间及跨源缺失独立保留"),
            ("EXECUTION_LABEL","T+1开盘标签、两侧费用、尾部成熟边界、非重叠及全日对照零增量")))
        return ExperimentPrecheckResult(checks,ExperimentResult(ExperimentOutcome.PASS,
            {"synthetic_rows":len(d),"hypotheses":len(HYPOTHESES)},{}))

    def execute(self,context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        base=Path(__file__).resolve().parents[1];hashes={};frames={}
        for name,(eid,path) in INPUTS.items():
            prior=context.predecessors[eid];expected={a.path:a.sha256 for a in prior.artifacts}
            source=base/eid/"artifacts/rex"/path
            digest=sha256(source.read_bytes()).hexdigest()
            if digest!=expected[path]:raise ValueError(f"changed formal source {eid}/{path}")
            hashes[name]={"experiment_id":eid,"artifact":path,"sha256":digest}
            frames[name]=pd.read_parquet(source);frames[name].attrs={}
        d,f,s,v,alignment=build(frames)
        if len(d)!=1535 or str(d.index[0].date())!="2020-06-05" or str(d.index[-1].date())!="2026-09-30":
            raise ValueError("original authorized development window differs")
        print("INPUTS",len(frames),"SIGNALS",len(s.columns),flush=True)
        rows,annual,inference,panels=run(d,f,s,v)
        artifacts=[]
        def save(name,value,kind):
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,
                allow_nan=False,default=str)+"\n",encoding="utf-8",newline="\n")
            artifacts.append(context.workspace.register_artifact(name,kind))
        for name,value,kind in (
            ("source_hashes.json",hashes,"formal_source_lineage"),
            ("opportunities.json",rows,"mechanism"),
            ("annual.json",annual,"mechanism"),
            ("inference.json",inference,"uncertainty"),
            ("hypothesis_definitions.json",[dict(zip(("id","primary_horizon","parent","role","hypothesis"),x)) for x in HYPOTHESES],"protocol"),
            ("coverage.json",{"sessions":len(d),"hypotheses":len(HYPOTHESES),"controls":11,
                "paths":len(rows),"annual_rows":len(annual),"quality_masks_used":False,
                "all_history_development_and_seen":True,
                "availability":"FX源日+2自然日08:00；其余美国源日期严格早于中国T日；ETF份额次中国交易日08:30；SGE/期货前日政策。均非逐日历史发布时间实证。",
                "missing_families":["DXY","GVZ","全球黄金ETF持仓和资金流","COT","央行购金","金铜/金油比"],
                "source_calendar_windows":"5/20/60为对应原生源观察数；跨源配对只用源日相同双腿。",
                "selection_history":"EX004—EX028所有历史结果已见，用户朋友建议加入后、本轮正式收益读取前冻结18假设；不声称独立样本外。",
                "price_roles":"同类/SGE比值为相对价格，不是真实ETF净值溢价；FXCM美元黄金×USD/CNH为换算代理。"},
             "coverage")):
            save(name,value,kind)
        for name,x in (("features",f),("signals",s),("valids",v),("alignment",alignment),
                       ("labels",panels),("daily",d)):
            x.to_parquet(context.workspace.path(name+".parquet"))
            artifacts.append(context.workspace.register_artifact(name+".parquet","mechanism"))
        print("PATHS",len(rows),"PRIMARY",len(inference),flush=True)
        return ExperimentResult(ExperimentOutcome.INCONCLUSIVE,
            {"hypotheses":len(HYPOTHESES),"paths":len(rows),"primary_inference":len(inference)},
            {"scope":"阶段二第一性原理收益假设重建及首轮固定机制普查；账户目标未复验，缺资源机制不评价。"},
            tuple(artifacts))
