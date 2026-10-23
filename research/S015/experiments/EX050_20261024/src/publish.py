"""Close the fixed allocation comparison with complete formal references."""
from hashlib import sha256
from pathlib import Path

from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest,
    ExperimentValidationScope,
)
from run import HERE, ROOT, EX, MODES, read, save, material, authenticate, context


NAMES={'fixed100':'固定100%','fixed50':'固定50%','fixed75':'固定75%',
       'risk_reject':'风险不许可则拒绝','risk_half':'风险不许可50%，否则100%'}
CHECKS={'return':'年化收益','relative_drawdown':'相对回撤','absolute_drawdown':'绝对回撤',
        'frequency_median':'频率中位','frequency_coverage':'频率覆盖'}


def refs_in(value):
    if isinstance(value,dict):
        if value.get('type')=='EvidenceRef':
            yield EvidenceRef.from_dict(value)
        else:
            for item in value.values():
                yield from refs_in(item)
    elif isinstance(value,list):
        for item in value:
            yield from refs_in(item)


def report():
    result=read(HERE/'others/results.json')
    analysis=read(HERE/'others/analysis.json')
    assert analysis['status']=='PASS'
    rows=result['rows']
    assert len(rows)==5 and result['qualified_centers']==0
    accounts={a['mode']:a for a in analysis['accounts'] if a['window']=='full'}
    lines=['# S015 P2：风险分配与恒定减仓的五臂对照','',
        'Status: COMPLETED','',
        '本实验完成了问题验证，但没有产出合格策略，也没有证实风险状态在此用途下优于一般减仓。风险拒绝被固定50%同时以更高收益、更低回撤压过；动态50%/100%相对固定75%仅增加329元净收益，同时增加1.233个百分点最大回撤。结果不足以把原风险预测认定为有效的周期分配组件，建议停止此固定风险阈值的直接分配路线。','',
        '已完成5个事前固定配置、10个正式窗口账户，另有2个串行技术重复场景。五臂434日中心、415日严格双门、两窗联合中心均为0/5。没有搜索参数、重新训练、登记新候选或进入阶段三/四；新增合格候选为0。','',
        '## 研究问题与固定契约','',
        'P2承接批次计划：A-path收益许可是否应与波动风险信息分工，以降低投入比例取代一概拒绝，从而保留盈利机会。竞争解释是风险分数仅对应整体参与强度，任何好处都能由普通减少投入解释。','',
        '五臂共同使用`CYCLE_TARGET + signal_cash_fraction / entry_cycle`。首次开仓计划被宿主采纳时，按可用现金锁定含买费预算和目标份额；后续补买受剩余预算与剩余数量共同约束。固定50%/75%也使用该契约，没有沿用旧账户冒充新对照，没有每日权益再平衡。持有期间市价变化会使净值仓位偏离开仓比例；下文日末平均敞口仅为描述。','',
        '固定A-path三日市场意图容器：path预测≥0许可；触发后连续三个正目标信号日，第四个信号日退出，不同日重复预测不提前退出，退出日不再入场。实际买入可迟到或补买，实际持有天数不保证正好三天。拒绝臂在空闲时还要求风险预测≤当时训练预测中位数；动态臂以此风险条件选择100%或50%，一次意图内比例不变化。','',
        '434日为2025-01-02至2026-10-21，415日为2025-02-06至2026-10-21，各自10万元空仓初始化。T日17:30决策、T+1执行；原1%限价买、市价卖、100份整手、0.001价格档位、每侧0.1%成本、DAILY_RANGE_V3、HFQ_RESEARCH；期末估值不强平。基准保持原LimitBuyHold合同。','',
        '## 连续账户结果','',
        '| 原型 | 434日净收益 | 434日年化 | 最大回撤 | 415日净收益/回撤 | 闭合周期 | 60日闭合中位 | ≥3笔窗口 | 费用（元） | 平均日末敞口 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        mode=row['parameters']['allocation_mode'];f=row['runs']['full'];c=row['runs']['s011_common'];a=accounts[mode]
        lines.append(f"| {row['candidate_id']} {NAMES[mode]} | {100*f['net_return']:.3f}% | {100*f['cagr']:.3f}% | {100*f['dd']:.3f}% | {100*c['net_return']:.3f}% / {100*c['dd']:.3f}% | {f['closed']} | {f['frequency_median']:.0f} | {f['frequency_good']}/{f['frequency_windows']} | {f['fees']:.2f} | {100*a['mean_end_day_exposure']:.3f}% |")
    benchmark=rows[0]['runs']['full']
    lines += ['',
        '首次模型生效为2025-02-27；之前持现。两个窗口均在该日前开始且同为10万元，因此各臂两窗净收益/回撤相同，年化分母与频率窗口数不同。不是把434日账户切片为415日，也不是两份独立验证。','',
        f"434日LimitBuyHold年化{100*benchmark['benchmark_cagr']:.6f}%，回撤{100*benchmark['benchmark_dd']:.6f}%。原中心要求年化≥{150*benchmark['benchmark_cagr']:.6f}%，回撤≤{80*benchmark['benchmark_dd']:.6f}%且≤25%；60日闭合交易中位≥6，375窗至少338窗有≥3笔。415日严格要求净收益>91.58029150000013%、回撤<7.248663749114126%，按原值判定，不四舍五入过门。",'',
        '| 原型 | 434日失败项目 | 415收益门 | 415回撤门 | 联合中心 |',
        '| --- | --- | --- | --- | --- |']
    for row in rows:
        fail='、'.join(CHECKS[k] for k,v in row['runs']['full']['checks'].items() if not v) or '无'
        lines.append(f"| {row['candidate_id']} | {fail} | 未通过 | 未通过 | 未通过 |")
    lines += ['',
        '所有臂频率条件都通过；核心问题是经济目标。没有把风险下降抵消收益硬门失败。32点扰动与费用压力未执行，中心不通过不进入完整资格验收。','',
        '## 风险信息是否具有针对性','',
        '拒绝臂相对100%回撤下降8.601个百分点，却少赚15724.20元，仅剩226.49元净收益。固定50%比拒绝臂多赚8559.69元，回撤还低5.172个百分点，因而风险拒绝在此原型没有成立。拒绝还改变后续空闲机会队列，不能解释成从100%账本简单删除某些交易。','',
        '动态半仓相对100%少赚3033.57元，回撤下降5.424个百分点；相对固定75%多赚328.98元，但回撤升高1.233个百分点、费用多591.62元、平均日末敞口高0.916个百分点（46.009%对45.093%）。固定75%并非事后拟合出的精确敞口匹配；这些结果只能说明没有清楚的针对性收益风险改善，不能证明任何情况下风险预测均无用。','',
        '| 原型 | 盈利周期金额合计（元） | 亏损周期金额绝对值（元） | 与100%相比盈利减少（元） | 与100%相比亏损减少（元） |',
        '| --- | ---: | ---: | ---: | ---: |']
    baseline=accounts['fixed100']
    for mode in MODES:
        a=accounts[mode]
        lines.append(f"| {NAMES[mode]} | {a['cycle_profit_yuan']:.2f} | {a['cycle_loss_yuan']:.2f} | {baseline['cycle_profit_yuan']-a['cycle_profit_yuan']:.2f} | {baseline['cycle_loss_yuan']-a['cycle_loss_yuan']:.2f} |")
    lines += ['',
        '表内金额来自各自完整真实账户，不是把基准收益乘比例；每个未闭合周期以期末收盘估值，不当成已闭合交易。两个账户盈利金额变化同时包含规模、复利、费用和机会队列差异，不能全部解释成风险分数识别出的金额。','',
        '## 能否识别入场当天亏损，会错过多少盈利','',
        '统一事件队列取模型已可得且A-path预测≥0的所有开发池信号日；每次独立10万元的历史事件可重叠，用于信息诊断，不能累加成连续账户收益。风险高组为风险预测大于当时训练预测中位数。沿用已认证EX036标签：entry为入场当日收盘损益减买费，net3为原三日事件完整净损益。旧标签没有变成新预算契约的分配账户。','',
        '| 标签 | 有效事件 / 缺失 | 风险高组事件 | 识别亏损金额 / 全亏损（元） | 亏损金额覆盖 | 同时错过盈利 / 全盈利（元） | 盈利金额遗漏 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for event in analysis['common_path_events']:
        lines.append(f"| {event['target']} | {event['n']} / {event['missing_labels']} | {event['selected_n']} | {event['selected_loss_yuan']:.2f} / {event['loss_denominator_yuan']:.2f} | {100*event['loss_fraction']:.3f}% | {event['selected_profit_yuan']:.2f} / {event['profit_denominator_yuan']:.2f} | {100*event['profit_fraction']:.3f}% |")
    actual=analysis['baseline_actual_cycles_risk_attribution']['entry_day_net_yuan']
    lines += ['',
        '入场日层面识别52.280%的亏损金额，却会排除55.756%的盈利金额，不能称为有针对性的避损。三日层面覆盖61.528%亏损、遗漏53.811%盈利，存在有限信息倾向，但没有兑现为连续账户优势。缺失标签单列，不能当作未亏损或未盈利。','',
        f"在新契约100%账户实际89个有成交周期中，以首次成交日对应信号的风险状态标记，高风险43个：入场日实际亏损金额覆盖{100*actual['loss_fraction']:.3f}%（{actual['selected_loss_yuan']:.2f}/{actual['loss_denominator_yuan']:.2f}元），盈利金额占{100*actual['profit_fraction']:.3f}%（{actual['selected_profit_yuan']:.2f}/{actual['profit_denominator_yuan']:.2f}元）。这是已成交队列归因，补买迟到可能改变首次成交对应风险状态；不声称这些金额可以原样避免。真正拒绝或半仓的经济效果应读五臂完整账户。",'',
        '## 损益路径、机制反证与下一步','',
        '| 原型 | 入场日毛损益（元） | 后续毛损益（元） | 实际费用（元） | 净损益（元） |',
        '| --- | ---: | ---: | ---: | ---: |']
    for mode in MODES:
        a=accounts[mode]
        lines.append(f"| {NAMES[mode]} | {a['entry_day_gross_yuan']:.2f} | {a['later_gross_yuan']:.2f} | {a['fees_yuan']:.2f} | {a['net_yuan']:.2f} |")
    lines += ['',
        '100%账户30060.40元入场日毛损益、6682.90元后续毛损益，被20792.61元实际费用显著消耗。风险拒绝的后续毛损益为−9104.30元，动态半仓为+10542.80元；这反映不同队列/权重，不能直接推出延长或缩短持有会改善，更不能重复EX045的“许可失效就卖”已否定域。P2本身没有产生新的、足以独立启动P3的持有条件，下一步是否检验持有价值由P1/P0联合证据决定。','',
        '固定100%实际周期按首次买入信号过去5日涨跌分组：上涨47个净17516.88元，下跌41个净1090.36元，零变动1个净−2656.56元。收益并非只来自过去下跌组，削弱“只是旧超跌入口换名”的简单解释；样本分组并不证明与S011经济机制独立，也不据此增加上涨筛选。','',
        '研究决定：停止本次固定风险中位数作为拒绝/周期半仓的直接用途，不在相邻风险阈值、仓位或三日期限上继续寻优。保留负面和机会代价证据；若要重新考虑风险分配，应有新的条件机制或持有信息证据，并明确重新设计及阶段边界。','',
        '## 因果、执行、正式认证与选择历史','',
        '完整复用经身份核验的EX042 A模型计划：20个发布日期、收益/风险两角色共40套模型，新拟合0。Ridge正则10，标准化与风险中位阈值都只来自当时已成熟标签；至少30个成熟样本，每20交易日更新。每个train_known_max严格早于生效日，运行时只用已生效参数。复用原独立训练审计，并完成25个物理截断特征/模型前缀核验。因果可得不等于独立预测有效。','',
        f"账户核验重建{analysis['runtime_prediction_rows']}行信号，核对{analysis['formal_ledger_exports']}份正式JSON与导出账本；实际绑定的价格字段重算特征与历史已认证特征一致。盘中Volume历史尾差继续披露，本策略只使用盘中OHLC；不将未用列等价性推广到新用途。十个账户均核对实际现金/持仓流、含费成本、首次预算、目标数量及周期内锁定、退出释放。每个分配臂有一例多次BUY周期，拒绝臂两例；不是单笔买入模型。",'',
        '首臂先显式1进程串行，再在公共evaluate_many中以最多4进程、每进程原生线程1重算；两个窗口result_hash及account_daily/decisions/orders/fills/trades五类账本逐值一致。串行账户也单独发布并保存导出，不仅记录布尔值。Optuna内存Study排队5个固定配置，保存全部trial状态/四个目标；不进行择优搜索。','',
        '初次公开diagnose_accounts认证返回INVALID_EVIDENCE，SE唯一失败码ENTRY_CYCLE_ALLOCATION_MISMATCH。最小反例是C5000在2025-03-10，周期精确含费成本98799.701000，与从binary64费用还原所得98799.70100000000001作精确比较产生1e-14误拒。初次失败证据原样保留。平台随后校正审计金额重建口径；本实验只读重新认证既有正式证据，没有改变研究参数、策略源码、账户账本、数据身份或新增账户评价。','',
        '修订后公开诊断先通过正式证据认证，再对动态分配明确返回UNSUPPORTED；该接口当前仅支持全仓单次买卖。上述损益拆分来自独立账本算术，未将其伪装为平台支持的账户诊断。初次前缀检查的None/NaN类型差异另有技术修订：仅核验表示归一化，保留已发布策略源码。','',
        '全部样本、方向和既有训练选择均已见过；五个配置不是五个独立机制，两窗和技术重复也不是独立验证。本轮没有外部数据接入、修改截止日或恢复历史候选资格。完整策略资格仍为0；本实验技术完成不等于用户总体目标已达成。','',
        '证据：[事前协议](protocols/allocation.json)、[全部账户](others/results.json)、[串行预检](others/serial_precheck.json)、[因果与契约核验](others/runtime_checks.json)、[独立分析](others/analysis.json)、[周期金额](others/cycle_accounting.csv)、[公开诊断](others/public_diagnoses.json)、[首次审计阻断](others/audit_blocker.json)、[技术检查修订](protocols/check_correction.json)。','']
    (HERE/'report.md').write_text('\n'.join(lines),encoding='utf-8',newline='\n')


def main():
    assert not (HERE/'others/published_refs.json').exists()
    authenticate()
    report()
    result=read(HERE/'others/results.json')
    references=[EvidenceRef.from_dict(row['evidence']) for row in result['rows']]
    references.append(EvidenceRef.from_dict(result['serial_evidence']))
    files=sorted(p for directory in ('src','protocols','others') for p in (HERE/directory).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.csv','.md')
                 and p.name!='published_refs.json')
    materials={}
    for path in files:
        if path.suffix=='.json':
            for ref in refs_in(read(path)):
                assert ref.experiment.strategy_id=='S015'
                ref.resolve(ROOT)
                references.append(ref)
        ref=material(path)
        materials[path.relative_to(HERE).as_posix()]=ref.to_dict()
        references.append(ref)
    ctx=context(1)
    report_ref=publish_evidence(ctx,ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),
        ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(references))))
    validation=validate_experiment(ctx.repository,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value=='PASS',validation.issues
    save(HERE/'others/published_refs.json',{'report':report_ref.to_dict(),'materials':materials,
        'evaluation_refs':[row['evidence'] for row in result['rows']],'serial_evidence':result['serial_evidence'],
        'validation':validation.to_dict()})
    print('P2_REPORT_PUBLISHED_VALIDATION_PASS',flush=True)


if __name__=='__main__':
    main()
