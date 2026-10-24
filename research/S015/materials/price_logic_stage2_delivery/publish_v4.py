"""Assemble stage-two prototype judgments without rewriting historical deliveries."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json,sys
from czsc_trader.application import RepositoryContext,assemble_delivery
from czsc_trader.research_tools import EvidenceRef,ExecutionResources,ResearchBatchRef
from czsc_trader.research_tools import delivery as d

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
HOME=Path(__file__).resolve().parent;BASE=ROOT/'research/S015/experiments'
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def ex(n):return BASE/f'EX{n:03d}_20261024'
if __name__ == '__main__':
    receipts={n:read(ex(n)/('others/published_report_v2.json' if n==70 else 'others/published_report.json')) for n in range(67,76)}
    materials={n:{k.replace('\\','/'):v for k,v in r['materials'].items()} for n,r in receipts.items()}
    def ref(n,path):return EvidenceRef.from_dict(materials[n][path])
    def definition(n):return d.ExperimentDefinitionRef(ref(n,'src/strategy_runtime/strategies/price_process.py'),'strategy_runtime.strategies.price_process.PriceProcess')
    def protocol(n):return ref(n,'protocols/plan.json' if n==67 else 'protocols/accounts.json')
    oldref=d.DeliveryReference.from_dict(read(ROOT/'research/S015/assets/deliveries/PROTOTYPES/2/receipt.json')['reference'])
    mandate=d.DeliveryReference.from_dict(read(ROOT/'research/S015/assets/deliveries/MANDATE/5/receipt.json')['reference'])

    COMPONENTS=[
     ('migration_discount',74,67,'SUPPORTED','入场：中心迁移背景下的收盘折让','EX067状态机会、旧PROTOTYPES/2删项及EX070结构内入场对照','组合用途得到支持；不把价格中心解释为资金成本或公允价值，具体3日优势仍含选择偏差。'),
     ('repair_anchor',74,71,'SUPPORTED','完成：价格回到机会激活时固定中心','完整原型 vs 删除完成目标/移动完成目标','删除完成目标仅2闭合周期且回撤36.39%；移动目标收益降低。固定目标避免中心下移伪装修复，账户增量包含交易队列。'),
     ('center_failure',74,73,'SUPPORTED','失效：当前中心退回机会激活时旧中心','同尺度完整原型 vs 纯锚修复；EX071/EX073','6组其他尺度均降低纯修复回撤并增加频率，多数牺牲收益；不保证支配固定期限。'),
     ('execution',74,75,'NOT_APPLICABLE','执行：T+1、资金周期、费用、限买市卖','标准与同身份费用翻倍、串并行、时钟及资金核对','已确认执行约束，不宣称独立创造收益；成交到达目标的偏差仍存在。'),
     ('moving_repair',71,71,'SUPPORTED','完成替代：价格达到当前中心','固定与移动修复目标','能结束折让状态但中心下降也可触发，整体收益低于固定目标，不建议替代主原型。'),
     ('fixed_timer',71,71,'NOT_APPLICABLE','历史控制：固定三信号日退出','固定退出 vs 有完成/失效定义的事件退出','保留数值优势或反例；尚无三日持有期与机会衰减相符的依据，不推荐为完整金融逻辑。'),
     ('price_origin',69,69,'INEFFECTIVE','失效替代：价格跌破激活时旧中心','宽入场与限制价格位于起点上方的入场','宽入场可已低于失效线；限制入场修补语义后收益降低，保留数值过线事实而不推荐。'),
     ('low_failure',68,68,'INEFFECTIVE','失效替代：价格跌破激活日低点','纯锚/移动修复 vs 日低点保护','当前原型下收益代价大，未提供优于中心失效的整体依据。'),
     ('gain_reversal',68,68,'INEFFECTIVE','失效替代：滚动中心增量转非正','纯锚修复 vs 滚动背景反转','起点每天移动，已有提前退出损失，整体证据弱于固定起点。'),
     ('trail_origin',69,69,'INEFFECTIVE','趋势持有：随新高抬升价格失败线','固定起点与跟踪起点','收益和回撤/频率代价未支持趋势承接，未证明另一独立收益来源。'),
     ('inside_gate',70,70,'INEFFECTIVE','入场限制：价格高于固定起点','同中心同退出宽入场 vs 结构内部入场','排除较深偏离会丢失有利机会；中心失效方案无需价格高于其线，主原型未保留该过滤。'),
     ('event_origin',72,72,'INEFFECTIVE','背景替代：最近一次中心上行段起点','固定代表尺度 vs 无固定天数事件起点','消除了固定观察天数但当前收益风险较弱，尚不能替代主原型；保留竞争解释。'),
     ('step_rearm',68,68,'INEFFECTIVE','再入场限制：等待新的中心正推进','同入口同退出即时再判断 vs 等待正推进','在锚修复方案未提供优势，不把旧固定期限控制中的收益推广到新退出。'),
     ('daily_center',70,70,'INEFFECTIVE','信息替代：日高低几何中点','均值/中位八根30分钟收盘中心 vs 日中点','本轮日中点未达到415双优；不能据此证明任何分钟信息都有增益。'),
    ]
    components=[]
    for cid,n,test,status,role,control,judgment in COMPONENTS:
     path='others/diagnosis.json' if test in (67,75) else 'others/results.json'
     t=d.ComponentTestResult(cid+'_test',ex(test).name,protocol(test),d.ComponentTestStatus(status),judgment,(ref(test,path),))
     components.append(d.ComponentEntry(cid,definition(n),role,'完整账户和用途对照；事件观察不冒充账户','T日完成信息形成意图，T+1执行，直至完成或失败',control,'T17:30约定；保留输入时钟等价已核验，历史供应商发布与修订时点未证明','HFQ研究状态、未复权实际执行；固定数据绑定','159326.SZ原434/415已见开发池及已确认执行合同',judgment,(t,)))
    component_map={c.component_id:c for c in components}
    EXIT_COMPONENTS={'fixed':['fixed_timer'],'repair':['moving_repair'],'anchor_repair':['repair_anchor'],'anchor_repair_reversal':['repair_anchor','gain_reversal'],'anchor_repair_floor':['repair_anchor','low_failure'],'repair_floor':['moving_repair','low_failure'],'anchor_origin':['repair_anchor','price_origin'],'origin_trail':['trail_origin'],'origin_only':['price_origin'],'anchor_center_origin':['repair_anchor','center_failure'],'center_origin_only':['center_failure'],'repair_center_origin':['moving_repair','center_failure']}
    JUDGMENT={'fixed':'固定持有期的业务依据缺口未解决，仅保留历史控制。','repair':'动态中心下降也能结束折让，收益不足以支持替代固定目标。','anchor_repair':'纯等待目标修复会长期占用资金，回撤和频率代价显著。','anchor_repair_reversal':'反转保护减少长期占用但盈利代价大，未优于中心固定起点方案。','anchor_repair_floor':'价格低点保护未提供更优的整体收益风险。','repair_floor':'移动目标和价格低点组合未解决收益差距。','anchor_origin':'价格失效与宽入场存在冲突；限制入场后的账户代价保留。','origin_trail':'趋势持有表达回撤/频率与收益不支持当前路线。','origin_only':'缺少完成目标，资金占用和频率明显不足。','anchor_center_origin':'固定完成线与中心失效线职责一致；本行是结构/尺度/源身份控制，发展由C7400/C7401承接。','center_origin_only':'删除完成目标后长期持有，只有2闭合周期、回撤36.39%，支持保留完成组件。','repair_center_origin':'同失效保护下移动修复目标降低整体收益，保留负面对照。'}
    limits=('所有历史已反复观察，434与415高度重叠；未新增独立验证。','只有3日均值/中位代表过415双优，其他尺度盈利不代表目标能力稳健。','中心只是价格状态量，非公平价值或资金流；参与者行为解释是待验证假设。','改变退出会改变交易队列、资金与费用，账户差不能直接作市场因果分解。','公开因果归因为UNSUPPORTED；独立账务核对不替代平台支持。','本轮未完成新原型阶段四全项自检、PBO或DSR，旧统计与候选资格保持历史身份。')
    prototypes=[];inventory=[];economic_groups={}
    for n in range(68,75):
     for r in read(ex(n)/'others/results.json')['rows']:
      cid=r['candidate_id'];p=r['parameters'];exit_=p.get('exit_mode','anchor_center_origin');mode=p.get('mode','center_below')
      ids=['migration_discount',*EXIT_COMPONENTS[exit_],'execution']
      if mode=='inside_advance':ids.append('inside_gate')
      if mode=='leg_below':ids.append('event_origin')
      if p.get('rearm_mode')=='positive_step':ids.append('step_rearm')
      if p['center_kind']=='daily_mid':ids.append('daily_center')
      disposition='DEVELOP' if n==74 else 'INVESTIGATE' if mode=='leg_below' else 'STOP'
      judge=JUDGMENT[exit_]
      if n==74:judge='推荐发展的完整原型：原中心经济、双频率和415双优通过，组件协作、跨尺度用途与成本得到支持；无固定持有期，尺度和成交偏差仍待完善。'
      elif mode=='leg_below':judge='无固定观察期的竞争表达，当前收益风险弱于主原型，不单独推进寻优；保留作为测量稳健性的补证对照。'
      f=r['runs']['full'];c=r['runs']['s011_common'];judge+=f" 434收益{f['net_return']:.6%}/回撤{f['dd']:.6%}；415收益{c['net_return']:.6%}/回撤{c['dd']:.6%}；联合中心条件={r['both_center_pass']}。"
      ev=[d.EvaluationEvidenceRef(EvidenceRef.from_dict(r['evidence']))]
      if n==74:
       sr=next(z for z in read(ex(75)/'others/results.json')['rows'] if z['candidate_id']==cid);ev.append(d.EvaluationEvidenceRef(EvidenceRef.from_dict(sr['evidence'])))
      source=(d.PrototypeReference(oldref,'P_MEAN_FIXED' if p['center_kind']=='mean' else 'P_MEDIAN_REPAIR' if p['center_kind']=='median' else 'P_DAILY_MID'),)
      evidence=(definition(n).evidence,ref(n,f'others/{cid}_payload.json'),protocol(n),ref(n,'others/results.json'))
      nxt='获准阶段三后固定主原型和均值对照，优先比较可观察折让空间与测量尺度，保留事件退出；若改善仅靠个别尺度或删掉少数亏损则回退。' if n==74 else '保持为不可变对照，不独立扩大当前表达搜索；必要补证由主原型的问题驱动。'
      hypothesis=f"中心定义{p['center_kind']}、背景{mode}、退出{exit_}；背景上移而收盘暂时低于中心可能形成条件修复机会。具体完成、失效及再入场表达由本身份源和参数决定，并用完整账户反驳或支持。"
      identity={'type':'CandidateIdentityRef',**r['identity'],'key':{'type':'CandidateKey',**r['identity']['key']}}
      prototypes.append(d.PrototypeEntry('P_'+cid,d.CandidateIdentityRef.from_dict(identity),definition(n),hypothesis,tuple(d.PrototypeComponentUse(i,component_map[i].role,'见对应事前用途检验与完整账户，不相加组件收益。') for i in ids),tuple(ev),d.PrototypeDisposition(disposition),judge,limits,nxt,evidence,sources=source))
      import pandas as pd
      signature=sha256(b''.join(pd.read_csv(ex(n)/f'others/{cid}_{w}_account_daily.csv')[['equity','cash','quantity']].to_numpy(float).tobytes() for w in ['full','s011_common'])).hexdigest()
      economic_groups.setdefault(signature,[]).append(cid)
      inventory.append({'experiment':ex(n).name,'candidate':cid,'parameters':p,'identity':r['identity'],'disposition':disposition,'judgment':judge,'both_center_pass':r['both_center_pass'],'runs':r['runs'],'account_path_group':signature})

    comparisons=[]
    for subject,control,n,question,answer in [
     ('C7401','C7400',74,'中位与均值代表是否一致支持机制？','两者中心/费用通过；中位收益风险更优，但同一家族、非两个独立发现。'),
     ('C7105','C7106',71,'中心失效保护的代价？','中位收益从160.94%降至111.20%，回撤从14.53%降至5.08%，恢复频率。'),
     ('C7105','C7107',71,'是否必须有完成目标？','无完成目标只有2闭合、24.19%收益及36.39%回撤。'),
     ('C7105','C7108',71,'固定目标还是移动目标？','固定目标111.20%/5.08%，移动目标79.65%/5.33%；不是以中心下降替代价格修复。'),
     ('C7105','C7109',71,'事件退出相对固定三日？','中位事件收益及回撤均更优；均值存在少量收益取舍，不宣称普遍支配。'),
     ('C7315','C7317',73,'10日反例是否保留？','中位事件收益较高但回撤较差；mean10事件两项均较差。'),
     ('C7206','C7209',72,'事件起点能否替代三日背景？','取消固定观察期后仍有收益，但当前收益/回撤较弱，暂不推进该替代。'),
     ('C7001','C7003',70,'更严格结构内入场是否改善？','更严格入场降低收益且增大回撤，深折让不能简单判定失效。'),
    ]:comparisons.append(d.PrototypeComparison('compare_'+subject+'_'+control,'P_'+subject,'P_'+control,question,protocol(n),(ref(n,'others/results.json'),),answer))
    conclusion='阶段二完成，使用9/20轮：形成一个有完整金融逻辑和组件协作证据的条件修复机制，C7401主原型、C7400均值对照建议发展；80个实现/配置身份全部留证，非80个独立发现。2 DEVELOP、2 INVESTIGATE、76 STOP（含已被最小实现承接的冻结控制）。164正式窗口账户+16技术账户；新原型完整阶段四合格数尚未判定。原16个阶段四数值合格保持。建议经用户批准再进入阶段三。'
    panel=d.PrototypePanel(tuple(prototypes),tuple(components),tuple(comparisons),conclusion)
    prior3=d.DeliveryReference.from_dict(read(ROOT/'research/S015/assets/deliveries/PROTOTYPES/3/receipt.json')['reference'])
    definition3=d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.PROTOTYPES,4,(prior3,oldref,mandate))
    direct=[]
    for n,receipt in receipts.items():
     direct.append(EvidenceRef.from_dict(receipt['report']))
     direct.extend(EvidenceRef.from_dict(v) for v in materials[n].values())
     if n>=68:
      result=read(ex(n)/'others/results.json');direct.extend(EvidenceRef.from_dict(r['evidence']) for r in result['rows']);direct.append(EvidenceRef.from_dict(result['serial_ref']))
    import os,re
    source_report=(HOME/'report.md').read_text(encoding='utf-8')
    report_base=ROOT/'research/S015/deliveries/PROTOTYPES/4'
    def rebase(match):
        label,target=match.groups()
        if '://' in target or target.startswith('#'):return match.group(0)
        absolute=(HOME/target).resolve()
        return '['+label+']('+Path(os.path.relpath(absolute,report_base)).as_posix()+')'
    published_report=re.sub(r'\[([^\]]*)\]\(([^)]+)\)',rebase,source_report)
    content=d.DeliveryContent(panel,d.DeliveryStatus.COMPLETE,(),(),report=published_report,evidence=tuple(dict.fromkeys(direct)))
    journal={'status':'TYPED_PANEL_PASS','rounds_used':9,'round_budget':20,'new_source_parameter_identities':80,'distinct_full_and_common_economic_paths':len(economic_groups),'formal_accounts':164,'technical_accounts':16,'dispositions':dict(Counter(p.disposition.value for p in prototypes)),'definition':definition3.to_dict(),'report_sha256':sha256(content.report.encode()).hexdigest(),'inventory':inventory,'economic_path_groups':economic_groups}
    assert journal['dispositions']=={'STOP':76,'INVESTIGATE':2,'DEVELOP':2}
    if sys.argv[1]=='check':
     save(HOME/'check_v4.json',journal);save(HOME/'panel_v4.json',panel.to_dict());print({k:journal[k] for k in ['status','rounds_used','new_source_parameter_identities','distinct_full_and_common_economic_paths','dispositions']},flush=True)
    else:
     assert sys.argv[1]=='publish' and read(HOME/'check_v4.json')==journal
     assert not (HOME/'publication_receipt_v4.json').exists()
     last=[None,0]
     def progress(v):
      if v.phase!=last[0] or v.elapsed_seconds-last[1]>=30:print(json.dumps(v.to_dict(),ensure_ascii=False),flush=True);last[:]=[v.phase,v.elapsed_seconds]
     result=assemble_delivery(RepositoryContext.discover(ROOT),definition3,content,resources=ExecutionResources(8,1,13),on_progress=progress)
     save(HOME/'publication_receipt_v4.json',{'status':'FULL_PUBLICATION_PASS' if result.validation.status is d.ValidationStatus.PASS else 'FAIL','assembly':result.to_dict()})
     assert result.validation.status is d.ValidationStatus.PASS
     print(json.dumps({'status':'FULL_PUBLICATION_PASS','reference':result.receipt.reference.to_dict()},ensure_ascii=False),flush=True)
