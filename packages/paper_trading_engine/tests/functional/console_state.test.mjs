import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {recordPage, ACCOUNT_REFRESH_SECTIONS, ScopedLoader, accountMarkup, accountOperatingStatus, actionLabel, actionsForRoute, auditCategoryLabel, auditEventLabel, auditOutcomeLabel, auditQuery, auditScopeLabel, auditSeverityLabel, auditSummary, channelMarkup, channelOrderAccountLabel, chartIsPending, chartShouldReload, chooseAccountId, comparisonQuery, decisionExecutionLabel, displayFillId, formatBeijingTime, formatPrice, formatQuantity, navigationOptions, orderPriceLabel, parseRoute, qualificationLabel, releaseVersionLabel, sideLabel, snapshotFingerprint, sortVirtualAccounts, statusLabel, systemAlertCount, systemEventLabel} from '../../src/paper_trading_engine/static/app.js';

test('forward chart keeps signal series, only fill markers on candles, and business details without IDs', () => {
  class Element {
    constructor(name){this.name=name;this.attributes={};this.children=[];this.style={};this.listeners={};this.classList={add(){}};this.clientWidth=1000;}
    setAttribute(key,value){this.attributes[key]=value;}
    appendChild(node){this.children.push(node);return node;}
    replaceChildren(...nodes){this.children=nodes;this._text='';}
    addEventListener(name,handler){this.listeners[name]=handler;}
    set textContent(value){this._text=value;this.children=[];}
    get textContent(){return (this._text||'')+this.children.map(node=>node.textContent).join('');}
    getBoundingClientRect(){return {left:0,top:0,width:1000,height:800};}
  }
  const nodes=Object.fromEntries(['pte-forward-chart','forward-stage','forward-svg','forward-tooltip','forward-context','forward-title','forward-subtitle','forward-asof','forward-event-date'].map(id=>[id,new Element(id)]));
  const observation=value=>({status:'READY',series:[{key:'score',label:'策略得分',value,guides:[{key:'threshold',label:'入场阈值',value:.2}]}],facts:[]});
  const context={
    strategy:{release_id:'S003-v1',name:'测试策略',symbol:'510500.SH',account_id:'s003-v1',release_hash:'current'},
    window:{selection_data_cutoff:'2026-09-02',observation_start:'2026-09-02'},
    market_data:{as_of:'2026-09-04',bars:['2026-09-02','2026-09-03','2026-09-04'].map(date=>({date,open:1,high:1.1,low:.9,close:1}))},
    observations:[
      {decision_id:'OLD',signal_date:'2026-09-02',valid_session:'2026-09-04',generated_at:'2026-09-02T12:30:00Z',action:'HOLD',observation:observation(.1)},
      {decision_id:'NEW',signal_date:'2026-09-02',valid_session:'2026-09-04',generated_at:'2026-09-03T12:30:00Z',action:'BUY',observation:observation(.3)},
      {decision_id:'LEGACY',signal_date:'2026-09-03',valid_session:'2026-09-04',generated_at:'2026-09-03T13:00:00Z',action:'BUY',observation:observation(.9)},
      {decision_id:'VOID',signal_date:'2026-09-02',valid_session:'2026-09-04',generated_at:'2026-09-03T14:00:00Z',action:'BUY',observation:observation(1.9)},
    ],
    execution:{
      decisions:[
        {decision_id:'TIMELINE',signal_date:'2026-09-03',valid_session:'2026-09-04',generated_at:'2026-09-04T09:00:00+08:00',action:'WAIT',status:'COMPLETED',target_quantity:0},
        {decision_id:'OLD',signal_date:'2026-09-02',valid_session:'2026-09-04',generated_at:'2026-09-02T12:30:00Z',action:'ROTATE',status:'SUPERSEDED',target_quantity:1000},
        {decision_id:'NEW',signal_date:'2026-09-02',valid_session:'2026-09-04',generated_at:'2026-09-02T17:30:00Z',action:'HOLD',status:'PENDING',target_quantity:0},
        {decision_id:'LEGACY',signal_date:'2026-09-03',valid_session:'2026-09-04',generated_at:'2026-09-03T13:00:00Z',action:'WAIT',status:'COMPLETED',state_reason:'NO_ORDER',state_changed_at:'2026-09-03T13:00:00Z',target_quantity:0},
        {decision_id:'VOID',signal_date:'2026-09-02',valid_session:'2026-09-04',generated_at:'2026-09-03T14:00:00Z',action:'BUY',status:'CANCELLED',state_reason:'CANCELLED',state_changed_at:'2026-09-03T14:00:00Z',target_quantity:5000},
        {decision_id:'WEEKEND',signal_date:'2026-09-04',valid_session:'2026-09-07',generated_at:'2026-09-05T03:00:00Z',action:'HOLD',status:'COMPLETED',state_reason:'NO_ORDER',state_changed_at:'2026-09-05T03:00:00Z',target_quantity:0},
      ],
      fills:[
        {fill_id:'<img>',channel_order_id:'O2',decision_id:'NEW',side:'SELL',quantity:400,price:1.2,fee:1,occurred_at:'2026-09-04T03:00:00Z'},
        {fill_id:'F1',channel_order_id:'O1',decision_id:'LEGACY',side:'BUY',quantity:100,price:1.2345,fee:.12,occurred_at:'2026-09-03T18:30:00Z'},
      ],snapshots:[],
    },
  };
  nodes['forward-context'].textContent=JSON.stringify(context);
  const window={listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},removeEventListener(){}};window.parent=window;
  runInNewContext(readFileSync(new URL('../../src/paper_trading_engine/static/forward-chart.js',import.meta.url),'utf8'),{
    window,document:{documentElement:new Element('html'),querySelector:selector=>nodes[selector.slice(1)],querySelectorAll:()=>[],createElement:name=>name==='canvas'?({getContext:()=>({measureText:text=>({width:text.length*7})})}):new Element(name),createElementNS:(_ns,name)=>new Element(name)},
    getComputedStyle:()=>({fontFamily:'sans-serif',getPropertyValue:()=> '#a78bfa'}),ResizeObserver:class{observe(){}},
  });
  const svg=nodes['forward-svg'];
  const points=()=>svg.children.filter(node=>node.attributes['data-series-key']==='score');
  assert.equal(points().length,2);
  assert.match(points()[0].attributes['aria-label'],/2026-09-02 策略得分 1.900/);
  assert.equal(svg.children.filter(node=>node.attributes['data-guide-key']==='threshold').length,2);
  assert.match(svg.textContent,/事件/);
  assert.match(svg.textContent,/2026-09-04 · 决策 1 笔 · 成交 2 笔/);
  assert.match(svg.textContent,/2026-09-04 02:30:00 · 成交：买入/);
  assert.match(svg.textContent,/2026-09-04 09:00:00 · 决策：等待/);
  assert.match(svg.textContent,/2026-09-04 11:00:00 · 成交：卖出/);
  assert.ok(svg.textContent.indexOf('02:30:00 · 成交')<svg.textContent.indexOf('09:00:00 · 决策'));
  assert.ok(svg.textContent.indexOf('09:00:00 · 决策')<svg.textContent.indexOf('11:00:00 · 成交'));
  assert.ok(!svg.textContent.includes('已失效'));
  assert.ok(!svg.textContent.includes('目标 5,000 股'));
  for(const text of ['买入 100 股','卖出 400 股','123.45 元','费用 0.12 元','2026-09-04 02:30:00'])assert.ok(svg.textContent.includes(text),text);
  assert.ok(svg.textContent.indexOf('买入 100 股')<svg.textContent.indexOf('卖出 400 股'));
  assert.equal(svg.children.filter(node=>node.attributes['data-fill-id']).length,2);
  assert.equal(svg.children.filter(node=>node.attributes['data-decision-id']).length,0);
  assert.equal(svg.children.filter(node=>node.attributes.class==='event-label').length,0);
  assert.equal(svg.children.filter(node=>node.name==='circle'&&!node.attributes['data-series-key']&&!node.attributes['data-guide-key']).length,2);
  const tooltip=nodes['forward-tooltip'];
  for(const text of ['OLD','NEW','LEGACY','VOID','F1','O1','O2','<img>','&lt;img&gt;','已失效','5,000 股'])assert.ok(!tooltip.innerHTML.includes(text),text);
  for(const text of ['行情（后复权）','开 / 高','低 / 收','2026-09-04'])assert.ok(tooltip.innerHTML.includes(text),text);
  for(const text of ['目标持仓','未记录','决策','成交','买入','卖出','费用'])assert.ok(!tooltip.innerHTML.includes(text),text);
  const overlay=svg.children.at(-1);
  overlay.listeners.pointermove({clientX:68,clientY:60});
  assert.match(svg.textContent,/2026-09-02 · 决策 1 笔/);
  assert.match(svg.textContent,/日内轮换/);
  assert.match(svg.textContent,/已替代/);
  assert.doesNotMatch(svg.textContent,/待执行/);
  assert.doesNotMatch(svg.textContent,/决策 0 笔|成交 0 笔/);
  assert.doesNotMatch(tooltip.innerHTML,/目标持仓|未记录|决策|成交/);
  overlay.listeners.pointermove({clientX:498,clientY:60});
  assert.match(svg.textContent,/2026-09-03 · 决策 3 笔/);
  assert.match(svg.textContent,/待执行/);
  assert.match(svg.textContent,/目标 0 股/);
  assert.match(svg.textContent,/2026-09-03 01:30:00 · 决策：持有/);
  assert.ok(svg.textContent.indexOf('01:30:00 · 决策')<svg.textContent.indexOf('21:00:00 · 决策'));
  assert.ok(svg.textContent.indexOf('21:00:00 · 决策')<svg.textContent.indexOf('22:00:00 · 决策'));
  assert.match(svg.textContent,/生效 2026-09-04；信号 2026-09-02/);
  assert.doesNotMatch(svg.textContent,/已替代|已失效/);
  const eventDate=nodes['forward-event-date'];
  assert.ok(eventDate.children.some(option=>option.value==='2026-09-05'&&option.textContent.includes('非交易日')));
  const candleCount=svg.children.filter(node=>node.name==='rect'&&node.attributes.stroke).length;
  eventDate.value='2026-09-05';eventDate.listeners.change();
  assert.match(svg.textContent,/2026-09-05 · 决策 1 笔 · 非交易日，无行情K线/);
  assert.match(svg.textContent,/状态原因：计划无需下单/);
  assert.equal(svg.children.filter(node=>node.name==='rect'&&node.attributes.stroke).length,candleCount);
  assert.equal(tooltip.hidden,true);
  assert.equal(svg.children.find(node=>node.attributes.class==='crosshair').style.display,'none');
  svg.children.at(-1).listeners.pointermove({clientX:928,clientY:60});
  nodes['forward-stage'].clientWidth=360;window.listeners.resize();
  assert.equal(points().length,2);
  assert.match(svg.textContent,/2026-09-04 · 决策 1 笔 · 成交 2 笔/);
  assert.equal(svg.children.filter(node=>node.attributes['data-fill-id']).length,2);
  assert.equal(svg.children.filter(node=>node.attributes['data-decision-id']).length,0);
});

test('FT-PTEJS01 console state preserves scope, stable polling and Chinese presentation', () => {
  assert.deepEqual(parseRoute('/accounts/s001-v2'), {page: 'account', accountId: 's001-v2'});
  assert.deepEqual(parseRoute('/channels/futu-simulate-cn'), {page: 'channel', channel: 'futu_simulate_cn'});
  assert.deepEqual(parseRoute('/comparison'), {page: 'comparison'});
  assert.deepEqual(parseRoute('/audit-events'), {page: 'audit'});
  const loader = new ScopedLoader();
  const oldRequest = loader.begin('baseline-143');
  const newRequest = loader.begin('s001-v2');
  assert.equal(loader.accept(oldRequest, 'baseline-143'), false);
  assert.equal(loader.accept(newRequest, 's001-v2'), true);
  assert.deepEqual(actionsForRoute({page: 'account'}), ['pause', 'resume']);
  assert.deepEqual(actionsForRoute({page: 'channel'}), ['pause', 'resume', 'cancel']);
  assert.equal(comparisonQuery(['alpha', 'beta']), 'account_id=alpha&account_id=beta');
  const first = {as_of: '2026-09-04T09:00:00Z', account: {cash: '100000.0000'}};
  const later = {as_of: '2026-09-04T09:00:05Z', account: {cash: '100000.0000'}};
  assert.equal(snapshotFingerprint(first), snapshotFingerprint(later));
  assert.equal(systemEventLabel('DATA_PUBLICATION_FAILED'), '发布数据失败');
  assert.equal(systemEventLabel('SERVICE_STARTED'), '服务启动');
  assert.equal(systemAlertCount({alerts: ['x'], scheduler_failures: [{operation: 'x'}]}), 2);
  assert.equal(releaseVersionLabel({release: {release_id: 'v0.5.2'}}), 'v0.5.2');
  assert.equal(releaseVersionLabel({}), '版本未知');
  assert.equal(chooseAccountId('baseline-143', [{account_id: 's001-v1'}], 's001-v1'), 's001-v1');
  assert.deepEqual(
    sortVirtualAccounts([
      {account_id:'s007-v1',symbol:'588080.SH',strategy_id:'S007'},
      {account_id:'s003-v1',symbol:'510500.SH',strategy_id:'S003'},
      {account_id:'s001-v2',symbol:'588080.SH',strategy_id:'S001'},
      {account_id:'s002-v1',symbol:'510500.SH',strategy_id:'S002'},
      {account_id:'s001-v1',symbol:'588080.SH',strategy_id:'S001'},
    ]).map(item=>item.account_id),
    ['s002-v1','s003-v1','s001-v1','s001-v2','s007-v1'],
  );
  assert.deepEqual(navigationOptions('s001-v1'), {showLoading: false, forceRender: false});
  assert.equal(channelOrderAccountLabel({account_id: 's001-v2'}), 's001-v2');
  assert.equal(formatBeijingTime('2026-09-03T11:00:11.806715+00:00'), '2026-09-03 19:00:11');
  assert.equal(displayFillId('9bce6fda-3e47-53b9-b4a6-f52410c6264a'), 'FIL-9BCE6FDA');
  assert.equal(orderPriceLabel({order_type: 'MARKET', limit_price: 0}), '市价');
  assert.equal(orderPriceLabel({payload: {order_type: 'MARKET'}, limit_price: '1.6090'}), '市价');
  assert.equal(orderPriceLabel({order_type: 'LIMIT', limit_price: '1.6500'}), '1.6500');
  assert.equal(actionLabel('WAIT'), '等待');
  assert.equal(actionLabel('HOLD'), '持有');
  assert.equal(sideLabel('SELL'), '卖出');
  assert.equal(qualificationLabel('PAPER_READY'), '获准模拟交易');
  assert.equal(statusLabel('CHANNEL_CASH_MISMATCH'), 'PTE账务现金与Futu现金不一致');
  assert.equal(statusLabel('FUTU_CASH_RECONCILIATION_UNATTRIBUTED'), 'Futu现金差异来源不明');
  assert.equal(statusLabel('FUTU_CASH_RECONCILIATION_OUT_OF_RANGE'), 'Futu费用差异超出允许范围');
  assert.equal(statusLabel('FUTU_CASH_RECONCILIATION_AMBIGUOUS'), 'Futu现金差异无法安全归属');
  assert.equal(accountOperatingStatus({run_state:'RUNNING',health:'BLOCKED'}), '阻塞');
  assert.equal(accountOperatingStatus({run_state:'PAUSED',health:'OK'}), '已暂停');
  assert.equal(formatPrice('1.5899999999999999'), '1.590');
  assert.equal(formatQuantity(60500), '60,500 股');
  assert.equal(decisionExecutionLabel({decision_id:'D1',action:'HOLD',status:'COMPLETED',state_reason:'NO_ORDER'}), '本次决策无需下单');
  assert.equal(decisionExecutionLabel({decision_id:'D2',action:'SELL',status:'COMPLETED'}), '已完成');
  assert.equal(decisionExecutionLabel(
    {decision_id:'D2',action:'SELL',status:'INCOMPLETE'},
    [{decision_id:'D2',status:'REJECTED'}, {decision_id:'D2',status:'FILLED_ALL'}],
  ), '未完成');
  assert.equal(decisionExecutionLabel({decision_id:'D3',action:'HOLD',status:'CANCELLED'}),'已取消');
  assert.equal(accountOperatingStatus({run_state:'PAUSED',health:'BLOCKED'}),'已暂停 · 阻塞');
  assert.equal(auditSummary({
    event_type:'ORDER_FILLED',details:{side:'SELL',quantity:60500,average_fill_price:1.589999999999},
  }), '卖出 60,500 股，成交均价 1.590');
  assert.equal(chartShouldReload(null, {scope: {account_id: 'a'}, fingerprint: 'f1'}), true);
  assert.equal(chartShouldReload(
    {account_id: 'a', fingerprint: 'f1'},
    {scope: {account_id: 'a'}, fingerprint: 'f1'},
  ), false);
  assert.equal(chartShouldReload(
    {account_id: 'a', fingerprint: 'f1'},
    {scope: {account_id: 'b'}, fingerprint: 'f1'},
  ), true);
  assert.equal(chartIsPending({status:'BUILDING'}), true);
  assert.equal(chartIsPending({status:'REFRESHING'}), true);
  assert.equal(chartIsPending({status:'READY'}), false);
  assert.equal(ACCOUNT_REFRESH_SECTIONS.includes('chart'), false);
  assert.equal(auditCategoryLabel('STRATEGY'), '策略事件');
  assert.equal(auditCategoryLabel('OTHER'), '其他事件');
  assert.equal(auditEventLabel('DECISION_GENERATED'), '生成决策');
  assert.equal(auditEventLabel('ORDER_FILLED'), '订单成交');
  assert.equal(auditEventLabel('ACCOUNT_STRATEGY_NAME_UPDATED'), '更新策略名称');
  assert.equal(auditEventLabel('BROKER_FEE_RECONCILED'), 'Futu费用对账');
  assert.equal(auditSummary({event_type:'BROKER_FEE_RECONCILED',details:{modeled_fee:'98.0403',actual_fee:'202.4380',adjustment:'-104.3977'}}), '估算费用 98.04，Futu实际费用 202.44，账务调整 -104.40');
  const accounts = [{account_id: 's001-v2', name: 'S001-v2模拟账户'}];
  assert.equal(
    auditScopeLabel({account_id: 's001-v2', channel: 'futu_simulate_cn'}, accounts),
    '虚拟账户 · S001-v2模拟账户（s001-v2）',
  );
  assert.equal(auditScopeLabel({account_id: null, channel: 'futu_simulate_cn'}, accounts), 'Futu模拟盘CN渠道');
  assert.equal(
    auditScopeLabel({event_type: 'DECISION_GENERATED', account_id: null, channel: 'futu_simulate_cn'}, accounts),
    '历史记录 · 虚拟账户未记录',
  );
  assert.equal(auditScopeLabel({account_id: null, channel: null}, accounts), '历史记录 · 作用域未记录');
  assert.equal(auditSeverityLabel('INFO'), '信息');
  assert.equal(auditOutcomeLabel('SUCCESS'), '成功');
  assert.equal(
    auditQuery({category: 'TRADING', account_id: 's001-v1', correlation_id: 'DEC 1'}),
    'category=TRADING&account_id=s001-v1&correlation_id=DEC+1',
  );
});

test('virtual account orders show order time and remain newest first', () => {
  const html = accountMarkup({
    scope: {account_id:'s001-v1',release_id:'S001-v1'},
    account: {account_id:'s001-v1',initial_cash:'100000',total_assets:'100000'},
    accounts: [{account_id:'s001-v1',release_id:'S001-v1'}],
    decision: {}, intents: [], fills: [], events: [], alerts: [], metrics: {},
    orders: [
      {account_id:'s001-v1',channel_order_id:'NEW',created_at:'2026-09-17T09:31:00+08:00'},
      {account_id:'s001-v1',channel_order_id:'OLD',created_at:'2026-09-17T09:30:00+08:00'},
    ],
  });
  assert.match(html, /下单时间/);
  assert.match(html, /<th>账户<\/th><th>Futu订单<\/th><th>下单时间<\/th>/);
  assert.ok(html.indexOf('2026-09-17 09:31:00') < html.indexOf('2026-09-17 09:30:00'));
});

test('retired account shows recovered cash and cannot be resumed', () => {
  const html = accountMarkup({
    scope: {account_id:'closed',release_id:'S001-v1'},
    account: {account_id:'closed',run_state:'RETIRED',initial_cash:'100000',
      cash:'0',total_assets:'0',released_cash:'101250.4321'},
    metrics: {current_total_return:0.012504321},
  });
  assert.match(html, /id="accountSwitch" disabled/);
  assert.match(html, /已退出 · 资金已回收/);
  assert.match(html, /已回收资金/);
  assert.doesNotMatch(html, /点击恢复/);
  assert.equal(accountOperatingStatus({run_state:'RETIRED'}), '已退出');
});

test('virtual account navigation excludes retired accounts and stale selections', () => {
  const accounts = [
    {account_id:'s002-v1',release_id:'S002-v1',run_state:'RETIRED',symbol:'510500.SH'},
    {account_id:'s011-v1',release_id:'S011-v1',run_state:'RUNNING',symbol:'159326.SZ'},
    {account_id:'s003-v1',release_id:'S003-v1',run_state:'PAUSED',symbol:'510500.SH'},
  ];
  assert.equal(chooseAccountId('s002-v1',accounts,'s002-v1'),'s011-v1');
  assert.equal(chooseAccountId(null,accounts,'s002-v1'),'s011-v1');
  assert.equal(chooseAccountId('s003-v1',accounts,'s011-v1'),'s003-v1');
  assert.equal(chooseAccountId('missing',accounts,'s003-v1'),'s003-v1');
  assert.equal(chooseAccountId('s002-v1',[accounts[0]],'s002-v1'),null);
  assert.equal(chooseAccountId(null,[],null),null);
  const html = accountMarkup({
    scope:{account_id:'s011-v1',release_id:'S011-v1'},
    account:{account_id:'s011-v1',run_state:'RUNNING'},
  },accounts);
  assert.doesNotMatch(html,/data-account="s002-v1"/);
  assert.doesNotMatch(html,/S002-v1/);
  assert.match(html,/data-account="s011-v1"/);
  assert.match(html,/data-account="s003-v1"/);
  assert.equal(accounts.length,3);
});

test('channel summary keeps four core metrics and moves reconciliation into details', () => {
  const snapshot = {
    account:{cash:756290.717,total_assets:1002769.617,market_value:246478.9},
    logical_cash:756290.717,logical_total_assets:996212.117,
    cash_difference:0,asset_difference:6557.5,
    strategy_allocated_capital:500000,unallocated_capital:500000,
    reconciliation_account:{cash:'-73.56'},reconciliation_status:'OK',
    accounts:[],orders:[],fills:[],alerts:[],paused:false,
  };
  const html = channelMarkup(snapshot);
  assert.equal((html.match(/class="panel metric"/g)||[]).length,4);
  assert.match(html,/资金对账正常/);
  assert.match(html,/估值口径不同/);
  assert.match(html,/<summary class="reconciliation-bar">/);
  assert.match(html,/<span class="reconciliation-trigger">查看明细<\/span>/);
  assert.match(channelMarkup(snapshot,true),/class="reconciliation-details" open/);
});


test('account record pagination bounds pages without losing or duplicating rows', () => {
  const rows=Array.from({length:25},(_,id)=>({id}));
  assert.deepEqual([1,2,3].flatMap(page=>recordPage(rows,page).rows),rows);
  assert.equal(recordPage(rows,100).page,3);
  assert.equal(recordPage(rows,-1).page,1);
  assert.equal(recordPage(rows,NaN).page,1);
  assert.deepEqual(recordPage([],2),{rows:[],page:1,pages:1,total:0});
  assert.equal(recordPage(rows.slice(0,5),3).page,1);
  assert.equal(rows.length,25);
});

test('account view separates history and preserves explicit reading state', () => {
  const snapshot={scope:{account_id:'demo',release_id:'S003-v1'},account:{account_id:'demo',symbol:'510500.SH'},
    orders:Array.from({length:25},(_,i)=>({channel_order_id:`ORDER-${i}`})),
    events:[{event_type:'HISTORICAL_SENTINEL'}],
    intents:[{attention_required:true,attention_reason:'REVIEW_REQUIRED',intent_id:'I1'}]};
  const html=accountMarkup(snapshot,[],{tab:'records',records:'orders',pages:{orders:2},accountDetails:true,decisionDetails:true});
  assert.match(html,/data-account-panel="chart" hidden/);
  assert.match(html,/S003-v1 · 510500.SH · Futu/);
  assert.match(html,/data-account-panel="records" >/);
  assert.match(html,/data-account-details="accountDetails" open/);
  assert.match(html,/data-account-details="decisionDetails" open/);
  assert.match(html,/第 2 \/ 3 页/);
  assert.match(html,/ORDER-10/);
  assert.doesNotMatch(html,/ORDER-20/);
  assert.doesNotMatch(html,/HISTORICAL_SENTINEL/);
  assert.match(html,/href="\/audit-events\?account_id=demo"/);
  assert.ok(html.indexOf('REVIEW_REQUIRED')<html.indexOf('role="tablist"'));
  assert.match(accountMarkup(snapshot,[]),/data-account-panel="records" hidden/);
});
