"""Lock document interpretation without loading outcome labels."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def main():
    target = EX/'protocols/annotations.json'
    if target.exists():
        raise RuntimeError('Preserve pre-unblind annotations')
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    docs = read(EX/'protocols/document_selection.json')['documents']
    matches = {x['doc_id']: x['matches'][0] for x in read(EX/'others/cninfo_requests.json')['matches']}
    # Page references are pages actually examined, not claims of full-document review.
    # category, direction, deduplicated event, examined pages, original facts / limitations
    specs = {
        'D01': ('GOVERNANCE_ROUTINE','neutral','2023H1',[1,2],'审议半年报并调整审计委员会；财务事项与D04去重。'),
        'D03': ('EARNINGS_OPERATING','mixed','2023H1',[1,2],'甲醇均价同比-11.52%，焦炉气-11.58%；不同量纲价格变化不能相减当利润率。'),
        'D04': ('EARNINGS_OPERATING','mixed','2023H1',[1,2,3,4],'营收-17.56%、归母净利润-8.93%、扣非-9.55%、经营现金流+17.01%；控制权转移为此前2月事项。'),
        'D05': ('CAPITAL_HOLDER','neutral','old-acquisition',[1,2,3,12,13],'收购持续督导：2022年签约、2023年2月过户，持股56.04%；不能当8月新收购。中间未读页不作无事项判断。'),
        'D06': ('EARNINGS_OPERATING','mixed','2024H1',[1,2,3,4],'营收-5.27%、归母+21.53%、扣非+5.19%、经营现金流-80.60%；盈利与现金流方向不同。'),
        'D09': ('GOVERNANCE_ROUTINE','neutral','2024H1',[1,2],'审议半年报及捐赠管理制度；财务事项去重。'),
        'D10': ('EARNINGS_OPERATING','mixed','2024H1',[1,2],'甲醇均价+1.69%、焦炉气+2.08%，不能据此直接推导毛利。'),
        'D12': ('EARNINGS_OPERATING','mixed','2024FY',[1,2,3,4,6],'营收-2.35%、归母+56.73%、扣非+56.24%、经营现金流-45.89%；不分红。'),
        'D18': ('GOVERNANCE_ROUTINE','neutral','auditor-renewal',[1,4],'续聘会计师事务所及审批程序；未完整审阅中间页，非审计风险排除结论。'),
        'D20': ('GOVERNANCE_ROUTINE','neutral','annual-meeting',[1,2,3],'通知5月6日年度股东大会，六项年度议案；不是新的经营结果。'),
        'D22': ('GOVERNANCE_ROUTINE','neutral','annual-board',[1,2,3,4,5],'年度报告、不分红、结构性存款与行动方案；分别与D12/D30/D31/D32去重。'),
        'D23': ('EARNINGS_OPERATING','mixed','2024FY',[1],'甲醇均价-0.03%、焦炉气+0.38%，年销量226100.66吨；属于年度经营事实。'),
        'D29': ('GOVERNANCE_ROUTINE','neutral','2024FY',[1,2,3],'监事会审议年度报告、不分红、内控等，重复相应实质事项。'),
        'D30': ('MATERIAL_CHANGE','unknown','wind-plan',[1,2],'行动计划：2024年已成立全资天玥新能源，拟拓展风电；探索资本公积弥补亏损、期货套保。均不等于已兑现利润或分红。首次披露未知。'),
        'D31': ('CAPITAL_HOLDER','neutral','deposit-authorization',[1,2,3],'自有资金结构性存款最高5.90亿元、单笔最长90天、授权12个月；不是新增已实现利润。'),
        'D32': ('CAPITAL_HOLDER','neutral','no-dividend-2024',[1,2],'期末未分配利润-1219496059.34元，拟2024年不分红；无预期基准，不自动当负面意外。'),
        'D34': ('GOVERNANCE_ROUTINE','neutral','annual-meeting',[1,2,3],'4月12日已通知会议的提示性公告，非新增实质议案。'),
        'D35': ('EARNINGS_OPERATING','mixed','2025Q1',[1],'甲醇均价+4.08%、焦炉气+14.74%；成本压力线索，不能当完整毛利模型。'),
        'D36': ('EARNINGS_OPERATING','mixed','2025Q1',[1,2,3],'营收-9.19%、归母+6.40%、扣非-2.37%、经营现金流由负转正；方向混合。其余财报页未逐页核查。'),
        'D37': ('GOVERNANCE_ROUTINE','neutral','annual-meeting-approved',[1,7],'股东大会法律意见，所读页为程序与有效性结论。'),
        'D38': ('GOVERNANCE_ROUTINE','neutral','annual-meeting-approved',[1,2],'5月6日会议决议，首页确认无否决议案；仅引用已读页，不声称完整审查全部表决表。'),
        'D39': ('EARNINGS_OPERATING','mixed','2025H1',[1,2],'甲醇均价-0.43%、焦炉气-0.20%，销量106803.46吨。'),
        'D41': ('EARNINGS_OPERATING','mixed','2025H1',[1,2,3],'营收-1.42%、归母+1.65%、扣非+5.31%、经营现金流+24.49%；有具体非行情事实，但无业绩意外基准。'),
        'D43': ('GOVERNANCE_ROUTINE','neutral','governance-2025',[1,2,3,4],'章程修订、取消监事会、审计委员会承接职责及换届安排；履历页未逐页核查。'),
        'D46': ('GOVERNANCE_ROUTINE','neutral','governance-2025',[1,2,3],'通知9月24日股东大会审议治理与换届事项。'),
        'D51': ('GOVERNANCE_ROUTINE','neutral','governance-2025',[1,2,18,24,28],'第24页章程规则允许按法定顺序用资本公积补亏；不是已经实施补亏或现金分红。仅所列页读证。'),
        'D56': ('GOVERNANCE_ROUTINE','neutral','investor-meeting-notice',[1],'通知9月15日15至17时业绩说明会，仅有未来会议安排，不能预知会议内容。'),
        'D57': ('EARNINGS_OPERATING','positive','2026H1',[1,2,3,4],'营收+1.95%、归母+31.42%、扣非+33.67%、经营现金流+104.52%；经营方向正向，不等于超预期。'),
        'D58': ('MATERIAL_CHANGE','unknown','wind-progress',[1,2,3,4],'隆化200MW项目已获核准，天玥增资1.5亿元事项1月已审议，已签4.36亿元设备合同、32台6.25MW机组；有经营事实增量，首次公开时间未知，不能当8月新催化。'),
        'D59': ('EARNINGS_OPERATING','mixed','2026H1',[1,2],'甲醇均价+7.80%、焦炉气+7.14%；销量101336吨，不由两种涨幅直接推导利润。'),
        'D61': ('GOVERNANCE_ROUTINE','neutral','2026H1',[1,2],'审议半年报及行动评估，与D57/D58去重。'),
        'D62': ('RISK_ABNORMAL','neutral','price-abnormal',[1,2],'8月28日、31日累计涨幅偏离超过20%；公司表示无未披露重大事项。主要重复已发生价格，非事前预警，也非不存在潜在风险的证明。'),
    }
    rows=[]
    for d in docs:
        spec=specs.get(d['doc_id'])
        rows.append({**d, 'cninfo_url':matches[d['doc_id']]['url'],
            'category':spec[0] if spec else 'UNKNOWN', 'direction':spec[1] if spec else 'unknown',
            'event_key':spec[2] if spec else None,'examined_pages':spec[3] if spec else [],
            'facts':spec[4] if spec else '未选读正文；不把目录标题当无实质信息或零事件。',
            'body_review': 'KEY_PAGES' if spec else 'UNREAD',
            'first_market_disclosure': 'UNVERIFIED', 'historical_revisions':'UNVERIFIED'})
    assert len(specs)==32 and {d['doc_id'] for d in docs if d['selected_for_body']}==set(specs)
    # Added before unblinding: do not confuse a short event window with persistent known state.
    reports={'D04':'2023H1','D06':'2024H1','D12':'2024FY','D36':'2025Q1','D41':'2025H1','D57':'2026H1'}
    cases=[]
    for c in read(EX/'others/blinded_cases.json'):
        window=[d for d in rows if c['lookback_start']<=d['date']<=c['exit_date']]
        eligible=[d for d in window if d['date']<c['signal_date']]
        prior_reports=[d for d in rows if d['doc_id'] in reports and d['date']<c['signal_date'] and d['date'][:4]==c['signal_date'][:4]]
        latest=max(prior_reports,key=lambda x:x['date']) if prior_reports else None
        cases.append({**c,'date_before_t':[d['doc_id'] for d in eligible],
            'same_day_time_unknown':[d['doc_id'] for d in window if d['date']==c['signal_date']],
            'post_decision':[d['doc_id'] for d in window if d['date']>c['signal_date']],
            'usable_reviewed':[d['doc_id'] for d in eligible if d['body_review']!='UNREAD'],
            'unread_before_t':[d['doc_id'] for d in eligible if d['body_review']=='UNREAD'],
            'financial_events_in_window':sorted({d['event_key'] for d in eligible if d['category']=='EARNINGS_OPERATING'}),
            'last_observed_report':latest['doc_id'] if latest else None,
            'last_observed_report_period':reports[latest['doc_id']] if latest else None})
    result={'annotation_stage':'LOCK_BEFORE_OUTCOME_UNMASK','documents':rows,'cases':cases,
        'timing':'仅SSE与CNInfo一致的官方日期；早于T可用，T日时间未知排除，T后不可用。ADDDATE和午夜epoch不作真实分钟证据。历史版本未知。',
        'carry_forward_addendum':'阅正文后、解盲前增加描述性检查：14日窗口衡量近期事件，不能抹掉此前已知财报。另列本次已抓取且同年T前最近报告，禁止把它冒充完整历史最后报告。无已抓取报告为UNKNOWN，不能判无财务信息。',
        'novelty':'财务/业务事实相对OHLCV有信息内容；相对市场此前已知信息的新颖性、是否意外、首次披露均未核实。',
        'visual_pages':['D04:2','D06:3','D12:4','D36:1','D41:2','D57:2','D58:2','D62:1','D51:24'],
        'limitations':['32份只核查列示关键页；30份正文未读，不推断无重要事项。','样本来自已见开发池且按收益分层，不是独立盲试。','来源搜索额外看到2025年6月及2024年12月、2025年1月、2026年3/5月同公司窗口外结果；未用来修改样本、计事件或评价收益。','未核验所有业绩预告、修订及市场预期，不把同比利润增长称为超预期。']}
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'documents':len(rows),'reviewed':len(specs),'cases':len(cases),'labels_read':False}))


if __name__=='__main__':
    main()
