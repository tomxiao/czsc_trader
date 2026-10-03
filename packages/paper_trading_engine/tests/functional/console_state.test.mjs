import assert from 'node:assert/strict';
import test from 'node:test';
import {ACCOUNT_REFRESH_SECTIONS, ScopedLoader, accountMarkup, accountOperatingStatus, actionLabel, actionsForRoute, auditCategoryLabel, auditEventLabel, auditOutcomeLabel, auditQuery, auditScopeLabel, auditSeverityLabel, auditSummary, channelMarkup, channelOrderAccountLabel, chartIsPending, chartShouldReload, chooseAccountId, comparisonQuery, decisionExecutionLabel, displayFillId, formatBeijingTime, formatPrice, formatQuantity, navigationOptions, orderPriceLabel, parseRoute, qualificationLabel, releaseVersionLabel, sideLabel, snapshotFingerprint, sortVirtualAccounts, statusLabel, systemAlertCount, systemEventLabel} from '../../src/paper_trading_engine/static/app.js';

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
  assert.equal(accountOperatingStatus({paused:false,status:'RUNNING',health:'BLOCKED'}), '阻塞');
  assert.equal(accountOperatingStatus({paused:true,status:'RUNNING',health:'OK'}), '已暂停');
  assert.equal(formatPrice('1.5899999999999999'), '1.590');
  assert.equal(formatQuantity(60500), '60,500 股');
  assert.equal(decisionExecutionLabel({decision_id:'D1',action:'HOLD'}, []), '本次决策无需下单');
  assert.equal(decisionExecutionLabel(
    {decision_id:'D2',action:'SELL'}, [{decision_id:'D2',status:'FILLED_ALL'}],
  ), '全部成交');
  assert.equal(decisionExecutionLabel(
    {decision_id:'D2',action:'SELL'}, [
      {decision_id:'D2',status:'REJECTED'}, {decision_id:'D2',status:'FILLED_ALL'},
    ],
  ), '全部成交（此前 1 次未成功）');
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
  assert.equal(
    auditScopeLabel({account_id: 's001-v2', channel: 'futu_simulate_cn'}, accounts),
    '虚拟账户 · S001-v2模拟账户（s001-v2）',
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
    account: {account_id:'closed',status:'RETIRED',paused:true,initial_cash:'100000',
      cash:'0',total_assets:'0',released_cash:'101250.4321'},
    metrics: {current_total_return:0.012504321},
  });
  assert.match(html, /id="accountSwitch" disabled/);
  assert.match(html, /已退出 · 资金已回收/);
  assert.match(html, /已回收资金/);
  assert.doesNotMatch(html, /点击恢复/);
  assert.equal(accountOperatingStatus({status:'RETIRED',paused:true}), '已退出');
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
