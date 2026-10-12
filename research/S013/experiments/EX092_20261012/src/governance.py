"""Bounded S013 EX089-EX098 declaration, public evidence and report-copy closeout."""
from pathlib import Path
from datetime import date
import sys

from czsc_trader.application import create_experiment,ExperimentRequest,assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-new-goal'
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_confirm_execution as base  # noqa: E402

read,write,digest,public,put=base.read,base.write,base.digest,base.public,base.put
AUTH={'human_message':'同意这版目标：用buyhold盈利年份合并交易频率替代全期频率硬门，中心及标准32个扰动点均须通过新版四门。再授权10轮实验，请自主研究，额度用完后暂停并给出通俗结论，每个实验目录保存report副本。',
      'human_doc_message':'请你顺手把实验报告的输出规范，写入RSCH文档',
      'maximum_additional_experiments':10,'reserved_experiment_sequence':[f'EX{i:03}' for i in range(89,99)],
      'last_allowed':'EX098','next_unapproved':'EX099','pause_after_quota':True,
      'round_definition':'每个EX编号一轮；技术修正/独立复算/同轮中心及32点/独立费用不另算；不得拆分账户规避额度',
      'scope':'S013 existing510500.SH development pool2020-01-02..2026-09-30;2019 permitted warmup;HFQ fixed anchor;cash1m;lot100;one-way10bp;1percent fixed LimitBuyHold',
      'new_gates':{'net_cagr':'at least1.5same positiveBH CAGR;otherwise strictlypositive',
       'annual_drawdown':'strictly smaller than sameBH every year,continuous previousyearend equity',
       'positive_buyhold_year_frequency':'all positiveBH years pooled actual closed exits*60/sessions>=4',
       'negative_buyhold_year_profit':'strategy actual continuous netreturn strictly>0 every negativeBH year'},
      'standard32':'center and all32 pass new4;normalised totalL2 radius.05;seed13;all effective numeric coordinates;domains prospective not narrowed after results',
      'annual_classification':'realised yearlyBH sign is ex-post acceptance only,never a strategy input or currentyear oracle',
      'fivechecks':'latest independent definitions;only standard32 creates new robustness hardgate;time/concentration/fee/statistical diagnostics add no extra veto',
      'all_pool_frequency':'report-only,not economic hardgate',
      'no_new_data_platform_production':True,'historical_eligibility_unchanged':True,
      'report_copy':'every final formal report exactbytes ->others/report.md;SHA+byte proof inprotocols/report_copy_verification.json'}


def allocate(number,*, title,question,plan,checks):
    if number not in range(89,99):
        raise ValueError('EX089-EX098 only; noEX099')
    if checks['status']!='PASS' or checks['real_inputs']!=0:
        raise ValueError('Synthetic check PASS before actual declaration')
    if number>89:
        prior=ROOT/f'research/S013/experiments/EX{number-1:03}_20261012/protocols'
        done=read(prior/'budget_receipt.json')
        if done['completed']!=number-89 or done['remaining']!=99-number:
            raise ValueError('Previous round must fully close')
        if read(prior/'delivery_validation.json')['status']!='PASS' or read(prior/'report_copy_verification.json')['status']!='PASS':
            raise ValueError('Previous FULL and report copy must PASS')
    for name,sha in plan['source_files'].items():
        if digest(ROOT/name)!=sha:
            raise ValueError('Source drift:'+name)
    for ref in plan['input_references'].values():
        public(ref)
    c=base.common()
    ctx=c.context(1)
    exp=create_experiment(ctx,ExperimentRequest(title,question,date(2026,10,12)))
    if exp.experiment_id!=f'EX{number:03}_20261012':
        raise ValueError('Allocation differs; never reallocate')
    path=exp.resolve(ROOT)
    plan={**plan,'experiment':exp.to_dict(),'quota_slot':number-88,'status':'FROZEN_BEFORE_REAL_STUDY'}
    write(path/'protocols/plan.json',plan)
    refs={'plan.json':put(ctx,exp,path/'protocols/plan.json')}
    authpath=path/'protocols/renewal_authorization.json'
    write(authpath,AUTH)
    refs['renewal_authorization.json']=put(ctx,exp,authpath)
    for name,sha in plan['source_files'].items():
        source=ROOT/name
        refs[name]=put(ctx,exp,source)
        if source.is_relative_to(WORK):
            dest=path/'src'/source.relative_to(WORK)
            dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as stream:
                stream.write(source.read_bytes())
    write(path/'protocols/method_references.json',refs)
    write(path/'protocols/started_budget.json',{'started':number-88,'completed':number-89,'remaining_unstarted':98-number,
           'authority':refs['renewal_authorization.json'],'pause_after_EX098':True})
    assert not c.SOURCE_CALLS
    return exp,plan,refs


def stage(number):
    exp=ExperimentRef('S013',f'EX{number:03}_20261012')
    path=exp.resolve(ROOT)
    plan=read(path/'protocols/plan.json')
    refs=read(path/'protocols/method_references.json')
    if read(public(refs['plan.json']))!=plan or read(public(refs['renewal_authorization.json']))!=AUTH:
        raise ValueError('Frozen declaration/authority drift')
    for name,sha in plan['source_files'].items():
        if digest(ROOT/name)!=sha:
            raise ValueError('Frozen source drift:'+name)
    return exp,path,plan,refs


def publish_mandate(exp,refs):
    c=base.common()
    ctx=c.context(1)
    oldpath=ROOT/'research/S013/assets/deliveries/MANDATE/6/delivery.json'
    old=read(oldpath)
    items=list(m.ResearchMandate.from_dict(old['content']['payload']).items)
    auth=EvidenceRef.from_dict(refs['renewal_authorization.json'])
    confirm=m.ConfirmationRecord(m.ConfirmationStatus.CONFIRMED,auth)
    items=[item for item in items if item.item_id!='trade_frequency']
    items.append(m.MandateItem('positive_year_frequency_v2',m.MandateItemKind.CONSTRAINT,
       '全部实际buyhold净收益>0自然年合并，实际闭合交易按退出日归年；60*闭合数/交易日>=4；全期频率只报告。该条件含年度选择，当前SE标准FULL_SAMPLE_FREQUENCY不表达它，按关联冻结gates_v2.py计算，不冒充公共全期指标。',confirm))
    items.append(m.MandateItem('standard32_all_four_v2',m.MandateItemKind.CONSTRAINT,
       '中心及事前标准32联合扰动全部通过新版四门；5%归一化总L2、seed13、HALF_EVEN/LINEAR。最终年度涨跌只用于事后验收，策略只能用当时信息。',confirm))
    items.append(m.MandateItem('renewal_ten_rounds',m.MandateItemKind.RESOURCE,
       '仅EX089–EX098最多10轮，额度用完暂停；每实验正式report完整副本及哈希核对。原数据/只做多/执行/费用/价格保持，不改平台或历史资格。',confirm))
    report='''# S013新版四门与十轮研究授权

用户批准以buyhold盈利年份合并频率替代全期频率硬门，中心及标准32点全部通过新版四门。原收益、逐自然年回撤和亏损年份严格盈利保持；年份最终结果只用于事后验收，不输入策略。

频率按真实闭合交易退出日期归属年度，未闭合不计，2026仅现有截止日。最新五项诊断仍独立，除32点四门外不新增经济否决门。当前平台通用全期频率指标不支持该年度选择，使用已关联冻结研究校验器明确计算；没有平台改动或冒充全期频率。

仅原S013510500开发池、HFQ锚及固定1%执行合同，100万元、100研究单位、单侧10bp。EX089–EX098总10轮，完成后暂停，无EX099授权。历史研究与资格不重写。

本交付确认目标与授权，不表示策略已经达标。新实验报告最终保存完整副本并核对字节、大小及SHA256。
'''
    predecessor=m.DeliveryReference.from_dict(read(ROOT/'research/S013/assets/deliveries/MANDATE/6/receipt.json')['reference'])
    evidence=tuple(EvidenceRef.from_dict(refs[k]) for k in ('renewal_authorization.json','.tmp/s013-new-goal/gates_v2.py'))
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.MANDATE,7,(predecessor,)),
            m.DeliveryContent(m.ResearchMandate(tuple(items)),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    write(exp.resolve(ROOT)/'protocols/mandate_v2_reference.json',receipt.reference.to_dict())
    write(exp.resolve(ROOT)/'protocols/mandate_v2_validation.json',validation.to_dict())
    if validation.status.value!='PASS':
        raise ValueError(validation.to_dict())
    return receipt.reference


def close_component(number,*, component_id,entrypoint,judgment,status,report,results):
    exp,path,plan,refs=stage(number)
    c=base.common()
    ctx=c.context(1)
    for name,file in results.items():
        refs[name]=put(ctx,exp,file)
    audit=read(public(refs['verification.json']))
    if audit['status']!='PASS':
        raise ValueError('Independent scientific audit must PASS')
    budget={'started':number-88,'completed':number-88,'remaining':98-number,'last_completed':exp.experiment_id,
          'next_allowed':f'EX{number+1:03}' if number<98 else None,
          'authority':refs['renewal_authorization.json'],'pause_after_EX098':True,'objective_achieved':False,
          'new_accounts_this_round':audit.get('new_accounts',0)}
    write(path/'protocols/budget_receipt.json',budget)
    refs['budget_receipt.json']=put(ctx,exp,path/'protocols/budget_receipt.json')
    source=next(k for k in refs if k.endswith('/kernel.py'))
    test=m.ComponentTestResult(component_id+'-TEST',exp.experiment_id,EvidenceRef.from_dict(refs['plan.json']),status,judgment,
                              tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json','verification.json')))
    entry=m.ComponentEntry(component_id,m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs[source]),entrypoint),
       plan['role_of_component'],plan['label'],plan['horizon'],plan['controls'],plan['availability'],
       plan['price_basis'],plan['limitations'],judgment,(test,))
    revisions=[int(p.name) for p in (ROOT/'research/S013/deliveries/COMPONENTS').iterdir() if p.name.isdigit()]
    revision=max(revisions)+1
    mandate=m.DeliveryReference.from_dict(read(ROOT/'research/S013/assets/deliveries/MANDATE/7/receipt.json')['reference'])
    prior=m.DeliveryReference.from_dict(read(ROOT/f'research/S013/assets/deliveries/COMPONENTS/{max(revisions)}/receipt.json')['reference'])
    evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(),*plan['input_references'].values())))
    report+='\n\n正式证据：\n\n'+''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.COMPONENTS,revision,(mandate,prior)),
            m.DeliveryContent(m.ComponentPanel((entry,),judgment),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    write(path/'protocols/delivery_reference.json',receipt.reference.to_dict())
    write(path/'protocols/delivery_validation.json',validation.to_dict())
    write(path/'protocols/closeout_references.json',refs)
    if validation.status.value!='PASS':
        raise ValueError(validation.to_dict())
    formal=ROOT/f'research/S013/deliveries/COMPONENTS/{revision}/report.md'
    copy=path/'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    if formal.read_bytes()!=copy.read_bytes():
        raise ValueError('Report copy differs')
    write(path/'protocols/report_copy_verification.json',{'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),
          'experiment_report':copy.relative_to(ROOT).as_posix(),'formal_sha256':digest(formal),'copy_sha256':digest(copy),
          'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,'exact_bytes':True})
    assert not c.SOURCE_CALLS
    return receipt.reference
