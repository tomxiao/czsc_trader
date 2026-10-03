export function parseRoute(pathname) {
  const account = pathname.match(/^\/accounts\/([^/]+)$/);
  if (account) return {page: 'account', accountId: decodeURIComponent(account[1])};
  if (pathname === '/channels/futu-simulate-cn') return {page: 'channel', channel: 'futu_simulate_cn'};
  if (pathname === '/comparison') return {page: 'comparison'};
  if (pathname === '/audit-events') return {page: 'audit'};
  return {page: 'account', accountId: null};
}

export class ScopedLoader {
  constructor(){this.sequence=0;this.scope=null;this.controller=null;}
  begin(scope){if(this.controller)this.controller.abort();this.controller=new AbortController();this.scope=scope;return {sequence:++this.sequence,scope,signal:this.controller.signal};}
  accept(request,scope){return request.sequence===this.sequence&&request.scope===scope;}
}

export const actionsForRoute = route => route.page==='channel'?['pause','resume','cancel']:route.page==='account'?['pause','resume']:[];
export const comparisonQuery = ids => ids.map(id=>`account_id=${encodeURIComponent(id)}`).join('&');
export const auditQuery = filters => {
  const query=new URLSearchParams();
  Object.entries(filters||{}).forEach(([key,value])=>{if(value!=null&&value!=='')query.set(key,value);});
  return query.toString();
};
export const auditCategoryLabel = value => ({STRATEGY:'策略事件',TRADING:'交易事件',SYSTEM:'系统事件',OTHER:'其他事件'}[value]||value||'未分类');
export const auditEventLabel = value => ({
  ACCOUNT_RETIRED:'账户退出并回收资金',
  MARKET_DATA_PUBLICATION_REQUESTED:'请求发布数据',MARKET_DATA_PUBLISHED:'发布数据成功',MARKET_DATA_PUBLICATION_FAILED:'发布数据失败',MARKET_DATA_OBSERVED:'验收SRT数据',MARKET_DATA_OBSERVATION_FAILED:'SRT数据验收失败',DECISION_GENERATED:'生成决策',DECISION_GENERATION_FAILED:'生成决策失败',ACCOUNT_DECISION_DRIVEN:'人工驱动账户决策',ACCOUNT_DECISION_DRIVE_FAILED:'人工驱动账户决策失败',DECISION_SUPERSEDED:'旧决策已失效',SIGNAL_TRIGGERED:'触发信号',SIGNAL_CLEARED:'信号解除',DECISION_EXPIRED:'决策过期',CHANNEL_STRATEGY_BOUND:'历史关系 · 渠道曾直接绑定策略',ACCOUNT_STRATEGY_BOUND:'虚拟账户绑定策略',ACCOUNT_STRATEGY_NAME_UPDATED:'更新策略名称',ACCOUNT_CHANNEL_BOUND:'虚拟账户绑定渠道',CHANNEL_RECONCILIATION_FAILED:'渠道对账失败',CHANNEL_RECONCILIATION_RECOVERED:'渠道对账恢复',
  EXECUTION_PLAN_LEG_READY:'计划环节就绪',EXECUTION_PLAN_BLOCKED:'执行计划阻塞',ORDER_INTENT_CREATED:'创建订单意图',ORDER_INTENT_RECOVERED:'恢复订单意图',ORDER_SUBMISSION_BLOCKED:'订单提交受阻',ORDER_SUBMITTED:'订单已提交',ORDER_SUBMISSION_FAILED:'订单提交失败',ORDER_REJECTED:'订单被明确拒绝',CANCEL_REQUESTED:'请求撤单',CANCEL_SUCCEEDED:'撤单成功',CANCEL_FAILED:'撤单失败',ORDER_PARTIALLY_FILLED:'订单部分成交',ORDER_FILLED:'订单成交',ORDER_TERMINATED:'订单终止',BROKER_FEE_RECONCILED:'Futu费用对账',
  SERVICE_STARTED:'服务启动',SERVICE_STOPPED:'服务停止',RESTART_REQUESTED:'请求重启',ACCOUNT_PAUSED:'账户暂停',ACCOUNT_RESUMED:'账户恢复',ACCOUNT_EXECUTION_MIGRATED:'账户执行关系迁移',ACCOUNT_RECONCILIATION_RECOVERED:'账户对账恢复',EXTERNAL_CALL_SUCCEEDED:'外部接口调用成功',EXTERNAL_CALL_FAILED:'外部接口调用失败',DEPENDENCY_DEGRADED:'外部依赖降级',DEPENDENCY_RECOVERED:'外部依赖恢复',SCHEDULER_OPERATION_FAILED:'调度任务失败',SCHEDULER_OPERATION_RECOVERED:'调度任务恢复',SCHEDULER_CYCLE_FAILED:'调度周期失败',VIRTUAL_ACCOUNT_FAILED:'虚拟账户运行失败',ACCOUNT_CHART_GENERATION_FAILED:'前瞻观察图生成失败',ACCOUNT_CHART_RECOVERED:'前瞻观察图恢复',LEGACY_EVENT:'历史事件',UNCLASSIFIED_EVENT:'未分类事件',
}[value]||value||'未知事件');
export const auditSeverityLabel = value => ({INFO:'信息',WARNING:'警告',ERROR:'错误',CRITICAL:'严重'}[value]||value||'未知');
export const auditOutcomeLabel = value => ({SUCCESS:'成功',FAILURE:'失败',REJECTED:'已拒绝',SKIPPED:'已跳过',UNKNOWN:'未知'}[value]||value||'未知');
export const auditScopeLabel = (event,accounts=[]) => {
  const account=accounts.find(item=>item.account_id===event?.account_id);
  const accountLabel=event?.account_id?`${account?.name||event.account_id}（${event.account_id}）`:null;
  if(accountLabel)return `虚拟账户 · ${accountLabel}`;
  if(event?.event_type==='DECISION_GENERATED'&&event?.channel==='futu_simulate_cn')return '历史记录 · 虚拟账户未记录';
  if(event?.channel==='futu_simulate_cn')return 'Futu模拟盘CN渠道';
  return '历史记录 · 作用域未记录';
};
export const snapshotFingerprint = value => JSON.stringify(value,(key,item)=>key==='as_of'?undefined:item);
export const chartShouldReload = (previous,status) => !previous||previous.account_id!==status?.scope?.account_id||previous.fingerprint!==status?.fingerprint;
export const chartIsPending = status => ['BUILDING','REFRESHING'].includes(status?.status);
export const systemEventLabel = value => ({
  DATA_PUBLICATION_FAILED:'发布数据失败',
  DATA_PUBLISHED:'数据发布成功',
  SCHEDULER_OPERATION_FAILED:'调度任务失败',
  SCHEDULER_OPERATION_RECOVERED:'调度任务恢复',
  SCHEDULER_CYCLE_FAILED:'调度周期失败',
}[value]||auditEventLabel(value));
export const systemAlertCount = value => (value?.alerts?.length||0)+(value?.scheduler_failures?.length||0);
export const releaseVersionLabel = value => value?.release?.release_id||'版本未知';
export function chooseAccountId(requested, accounts, defaultAccountId){
  const visible=accounts.filter(item=>item.status!=='RETIRED');
  if(visible.some(item=>item.account_id===requested))return requested;
  if(visible.some(item=>item.account_id===defaultAccountId))return defaultAccountId;
  return sortVirtualAccounts(visible)[0]?.account_id??null;
}
export const navigationOptions = renderedScope => ({showLoading:renderedScope==null,forceRender:false});
export const channelOrderAccountLabel = order => order?.account_id||order?.virtual_account_id||'历史未记录';
export const displayFillId = value => value?`FIL-${String(value).split('-',1)[0].toUpperCase()}`:'—';
export const orderPriceLabel = order => String(order?.order_type||order?.payload?.order_type||'LIMIT').toUpperCase()==='MARKET'?'市价':order?.limit_price;
export const sideLabel = value => ({BUY:'买入',SELL:'卖出',ROTATE:'日内轮换'}[String(value||'').toUpperCase()]||value||'—');
export const planRoleLabel = value => ({CORE_SETUP:'建立核心仓位',ROTATION_ENTRY:'开盘轮换买入',ROTATION_EXIT:'午间轮换卖出'}[value]||'普通订单');
export const qualificationLabel = value => ({PAPER_READY:'获准模拟交易',LIVE_READY:'获准实盘交易',RESEARCH:'研究中'}[value]||value||'—');
export const formatPrice = value => value==null||value===''?'—':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:3,maximumFractionDigits:3});
export const formatQuantity = value => value==null?'—':`${Number(value).toLocaleString('zh-CN')} 股`;
export function formatBeijingTime(value){
  if(!value)return '—';
  const date=new Date(value);if(Number.isNaN(date.getTime()))return String(value);
  const parts=Object.fromEntries(new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(date).filter(item=>item.type!=='literal').map(item=>[item.type,item.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

const esc = value => String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => value==null?'—':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct = value => value==null?'—':`${(Number(value)*100).toFixed(2)}%`;
const shortHash = value => value?String(value).slice(0,10):'—';
export const actionLabel = value => ({BUY:'买入',SELL:'卖出',ROTATE:'日内轮换',WAIT:'等待',HOLD:'持有'}[value]||value||'等待');
export const statusLabel = value => ({READY:'就绪',RUNNING:'运行中',OK:'正常',CONNECTED:'已连接',DEGRADED:'降级',PAPER_READY:'获准模拟交易',LIVE_READY:'获准实盘交易',BLOCKED:'阻塞',UNAVAILABLE:'不可用',ACCOUNT_CHART_UNAVAILABLE:'前瞻观察图不可用',CHANNEL_UNAVAILABLE:'Futu不可用',CHANNEL_CASH_MISMATCH:'PTE账务现金与Futu现金不一致',CHANNEL_RECONCILIATION_BLOCKED:'渠道对账阻塞',FUTU_CASH_RECONCILIATION_UNATTRIBUTED:'Futu现金差异来源不明',FUTU_CASH_RECONCILIATION_OUT_OF_RANGE:'Futu费用差异超出允许范围',FUTU_CASH_RECONCILIATION_AMBIGUOUS:'Futu现金差异无法安全归属',VIRTUAL_ACCOUNT_BLOCKED:'虚拟账户阻塞',ORDER_SUBMISSION_UNRESOLVED:'存在下单结果待确认',DATA_PUBLICATION_FAILED:'发布数据失败',DATA_PUBLICATION_OVERDUE:'数据发布超期',PUBLICATION_CALENDAR_UNAVAILABLE:'发布所需交易日历不可用',DECISION_GENERATION_OVERDUE:'决策生成超期',SCHEDULER_STALLED:'调度器停滞',SCHEDULER_OPERATION_FAILED:'调度任务失败',WAITING_DEPENDENCY:'等待前序成交及计划时点',PENDING_SUBMIT:'待提交',SUBMITTING:'提交中',SUBMISSION_UNCERTAIN:'提交结果待确认',SUBMISSION_FAILED:'提交失败',SUPERSEDED:'已被新决策替代',REJECTED:'已拒绝',EXPIRED:'已过期',TIMEOUT:'结果未知',SUBMITTED:'已提交',FILLED_PART:'部分成交',FILLED_ALL:'全部成交',CANCELLING_ALL:'撤单中',SUBMIT_FAILED:'提交失败',CANCELLED_PART:'部分成交后撤单',CANCELLED_ALL:'已撤销',FAILED:'失败',DISABLED:'已失效',DELETED:'已删除',FILL_CANCELLED:'成交已撤销',PENDING:'待执行'}[value]||value||'—');
export const accountOperatingStatus = account => account.status==='RETIRED'?'已退出':account.paused?'已暂停':statusLabel(account.health||account.status);
export function decisionExecutionLabel(decision,intents=[]){
  if(!decision?.decision_id)return '等待生成决策';
  if(['WAIT','HOLD'].includes(String(decision.action||'').toUpperCase()))return '本次决策无需下单';
  const related=intents.filter(item=>item.decision_id===decision.decision_id);
  if(!related.length)return '尚未创建订单意图';
  const latest=related.reduce((current,item)=>{
    const currentTime=Date.parse(current.created_at||'');
    const itemTime=Date.parse(item.created_at||'');
    if(Number.isFinite(itemTime)&&(!Number.isFinite(currentTime)||itemTime>currentTime))return item;
    return !Number.isFinite(itemTime)&&!Number.isFinite(currentTime)?item:current;
  });
  const failed=related.filter(item=>item!==latest&&['REJECTED','SUBMISSION_FAILED','SUBMIT_FAILED','TIMEOUT'].includes(item.status)).length;
  return `${statusLabel(latest.status)}${failed?`（此前 ${failed} 次未成功）`:''}`;
}
export function auditSummary(event){
  const detail=event?.details||event?.payload||{};
  if(['ORDER_FILLED','ORDER_PARTIALLY_FILLED'].includes(event?.event_type))return `${sideLabel(detail.side)} ${formatQuantity(detail.quantity)}，成交均价 ${formatPrice(detail.average_fill_price)}`;
  if(event?.event_type==='ORDER_SUBMITTED')return `${sideLabel(detail.side)} ${formatQuantity(detail.quantity)}，${String(detail.order_type||'LIMIT').toUpperCase()==='MARKET'?'市价单':`限价 ${formatPrice(detail.limit_price)}`}`;
  if(event?.event_type==='DECISION_GENERATED')return `${actionLabel(detail.action)}，目标持仓 ${formatQuantity(detail.target_quantity)}`;
  if(event?.event_type==='SIGNAL_TRIGGERED')return `${sideLabel(detail.side)} ${formatQuantity(detail.quantity)}`;
  if(event?.event_type==='BROKER_FEE_RECONCILED')return `估算费用 ${money(detail.modeled_fee)}，Futu实际费用 ${money(detail.actual_fee)}，账务调整 ${money(detail.adjustment)}`;
  if(event?.event_type==='EXTERNAL_CALL_SUCCEEDED')return `${detail.service||'外部服务'} · ${detail.operation||'调用'}成功`;
  if(event?.event_type==='EXTERNAL_CALL_FAILED')return `${detail.service||'外部服务'} · ${detail.operation||'调用'}失败`;
  return '详见“审计事件”页面';
}
const state = {accounts:[],loader:new ScopedLoader(),lastSuccess:null,renderedScope:null,fingerprint:null,system:null,systemFingerprint:null,chart:null};

async function getJson(url, options={}) {
  const response=await fetch(url,options);let payload={};
  try{payload=await response.json();}catch{payload={error:`HTTP ${response.status}`};}
  if(!response.ok)throw new Error(payload.error||`HTTP ${response.status}`);return payload;
}
function post(url,body={}){return getJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
function toast(message){const el=document.querySelector('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2200);}
function setNav(page){document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav===page));}

function renderEventDetails(payload){return `<details><summary>查看详情</summary><pre>${esc(JSON.stringify(payload||{},null,2))}</pre></details>`;}
function renderSystemEvents(s){
  const alerts=[...(s.alerts||[]).map(code=>({label:statusLabel(code),detail:{code}})),...(s.scheduler_failures||[]).map(item=>({label:'失败任务',detail:item}))];
  const active=alerts.length?alerts.map(item=>`<div class="event active-event"><strong>${esc(item.label)}</strong>${renderEventDetails(item.detail)}</div>`).join(''):'<div class="empty">当前没有活动告警</div>';
  const history=(s.events||[]).length?(s.events||[]).map(item=>`<div class="event"><div class="event-title"><strong>${esc(systemEventLabel(item.event_type))}</strong><time>${esc(formatBeijingTime(item.created_at))}</time></div>${renderEventDetails(item.payload)}</div>`).join(''):'<div class="empty">暂无系统事件</div>';
  document.querySelector('#systemEventsContent').innerHTML=`<section><h3>活动告警</h3>${active}</section><section><h3>最近事件</h3>${history}</section>`;
}
function openSystemEvents(){if(state.system)renderSystemEvents(state.system);const dialog=document.querySelector('#systemEventsDialog');if(dialog.showModal)dialog.showModal();else dialog.setAttribute('open','');}
async function refreshSystem(){const version=document.querySelector('#releaseVersion');try{const s=await getJson('/api/system/status');const fingerprint=snapshotFingerprint(s);const changed=fingerprint!==state.systemFingerprint;state.system=s;state.systemFingerprint=fingerprint;const count=systemAlertCount(s);const release=releaseVersionLabel(s);version.textContent=release;version.classList.toggle('warning',release==='版本未知');const status=document.querySelector('#systemStatus');status.textContent=`PTE ${statusLabel(s.runtime)} · Futu模拟盘CN ${statusLabel(s.futu_connection)} · 全局告警 ${count} · 查看系统事件`;status.classList.toggle('warning',count>0);if(changed&&document.querySelector('#systemEventsDialog')?.open)renderSystemEvents(s);}catch(error){version.textContent='版本未知';version.classList.add('warning');document.querySelector('#systemStatus').textContent=`系统状态不可用 · ${error.message}`;}}
function metric(label,value){return `<div class="panel metric"><label>${label}</label><strong>${value}</strong></div>`;}
function rowsTable(columns,rows){if(!rows?.length)return '<div class="empty">暂无记录</div>';return `<div class="table-wrap"><table><thead><tr>${columns.map(c=>`<th>${c[0]}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(c=>{const title=c[2]?.(row);return `<td${title?` title="${esc(title)}"`:''}>${esc(c[1](row))}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>`;}
function alerts(items){return (items||[]).map(item=>`<div class="alert">${esc(item.message||item)}</div>`).join('');}

export const ACCOUNT_REFRESH_SECTIONS=['sidebar','hero','alerts','metrics','decision','intents','orders','fills','performance'];
export function sortVirtualAccounts(accounts){
  const compare=(left,right)=>String(left||'\uffff').localeCompare(String(right||'\uffff'),'en',{numeric:true,sensitivity:'base'});
  return [...(accounts||[])].sort((left,right)=>compare(left.symbol,right.symbol)||compare(left.strategy_id||left.release_id,right.strategy_id||right.release_id)||compare(left.account_id,right.account_id));
}
const accountViews=new Map();
function accountView(accountId){
  if(!accountViews.has(accountId))accountViews.set(accountId,{tab:'chart',records:'intents',pages:{intents:1,orders:1,fills:1},accountDetails:false,decisionDetails:false});
  return accountViews.get(accountId);
}
export function recordPage(rows,page=1){
  const pages=Math.max(1,Math.ceil(rows.length/10));
  const current=Math.max(1,Math.min(pages,Number.isInteger(page)?page:1));
  return {rows:rows.slice((current-1)*10,current*10),page:current,pages,total:rows.length};
}
function accountRecords(kind,title,columns,rows,view){
  const page=recordPage(rows,view.pages?.[kind]);
  return `<section id="record-panel-${kind}" role="tabpanel" aria-labelledby="record-tab-${kind}" ${(view.records||'intents')===kind?'':'hidden'} class="panel section" data-account-section="${kind}" data-record-panel="${kind}"><div class="section-head"><h2>${title}</h2><span class="subtle">共 ${page.total} 条</span></div>${rowsTable(columns,page.rows)}<div class="record-pagination"><span>第 ${page.page} / ${page.pages} 页 · 每页 10 条</span><button type="button" class="button" data-record-page="${page.page-1}" data-record-kind="${kind}" ${page.page===1?'disabled':''}>上一页</button><button type="button" class="button" data-record-page="${page.page+1}" data-record-kind="${kind}" ${page.page===page.pages?'disabled':''}>下一页</button></div></section>`;
}
export function accountMarkup(snapshot,accountList=state.accounts,view={}){
  const a=snapshot.account,m=snapshot.metrics||{},d=snapshot.decision||{},scope=snapshot.scope,intents=snapshot.intents||[],orders=snapshot.orders||[],fills=snapshot.fills||[];
  const executionState=decisionExecutionLabel(d,intents);
  const accounts=sortVirtualAccounts(accountList.filter(item=>item.status!=='RETIRED'));
  const gapActions=intents.filter(item=>item.attention_required).map(item=>`<div class="alert execution-gap"><strong>前瞻执行缺口</strong> · ${esc(item.attention_reason||statusLabel(item.status))}<button class="button secondary" type="button" data-ack-intent="${esc(item.intent_id)}">复核后确认</button></div>`).join('');
  const tab=view.tab||'chart',recordTab=view.records||'intents';
  return `<div class="layout account-layout" data-account-page data-account-id="${esc(scope.account_id)}">
    <aside class="sidebar" data-account-section="sidebar"><h2>虚拟账户</h2><label class="account-picker">切换账户<select id="accountPicker">${accounts.map(item=>`<option value="${esc(item.account_id)}" ${item.account_id===scope.account_id?'selected':''}>${esc(item.name||item.account_id)} · ${esc(statusLabel(item.health))}</option>`).join('')}</select></label><div class="account-cards">${accounts.map(item=>`<button class="account-card ${item.account_id===scope.account_id?'active':''}" data-account="${esc(item.account_id)}"><strong>${esc(item.name)}</strong><small>${esc(item.release_id)} · ${item.paused?'已暂停':statusLabel(item.health)}</small><small>资产 ${money(item.total_assets)}</small></button>`).join('')}</div></aside>
    <div class="workspace">
      <section class="panel hero account-hero" data-account-section="hero"><div class="account-heading"><h1>${esc(a.name)}</h1><div class="subtle">${esc(scope.release_id)} · ${esc(a.symbol)} · Futu · ${esc(statusLabel(a.health))}</div></div><div class="account-actions"><a class="button" data-account-audit href="/audit-events?${auditQuery({account_id:scope.account_id})}">审计事件</a><button id="accountSwitch" ${a.status==='RETIRED'?'disabled':''} class="switch ${a.paused?'paused':''}" role="switch" aria-checked="${!a.paused}">${a.status==='RETIRED'?'已退出 · 资金已回收':a.paused?'已暂停 · 点击恢复':'自动运行 · 点击暂停'}</button></div><details class="account-details" data-account-details="accountDetails" ${view.accountDetails?'open':''}><summary>账户详情</summary><div class="kv"><div><span>账户 ID / 策略</span>${esc(scope.account_id)} · ${esc(a.strategy_name_snapshot)}</div><div><span>内容身份 / 资格</span>${esc(scope.release_hash)} · ${esc(qualificationLabel(a.qualification_snapshot))}</div><div><span>选择截止 / 观察起点</span>${esc(a.selection_data_cutoff)} / ${esc(a.observation_start)}</div><div><span>账务更新 / 日终估值</span>${esc(formatBeijingTime(a.updated_at))} / ${esc(a.last_settlement_session)}</div></div></details></section>
      <div data-account-section="alerts">${alerts(snapshot.alerts)}${gapActions}</div>
      <div class="grid account-metrics" data-account-section="metrics">${metric(a.status==='RETIRED'?'已回收资金':'总资产',money(a.status==='RETIRED'?a.released_cash:a.total_assets))}${metric('当前累计收益',pct(m.current_total_return))}${metric('可用现金',money(a.cash))}${metric('冻结资金',money(a.frozen_cash))}${metric('持仓',formatQuantity(a.quantity))}</div>
      <section class="panel account-decision" data-account-section="decision"><details data-account-details="decisionDetails" ${view.decisionDetails?'open':''}><summary><strong>最新决策 · ${esc(actionLabel(d.action))}</strong><span>目标 ${formatQuantity(d.target_quantity)}</span><span>有效交易日 ${esc(d.valid_session||'—')}</span><span>${esc(executionState)}</span><span class="subtle">详情</span></summary><div class="kv"><div><span>决策 ID</span>${esc(d.decision_id||'—')}</div><div><span>信号日期</span>${esc(d.signal_date||'—')}</div><div><span>执行参考价（不复权）</span>${formatPrice(d.execution_reference_price)}</div></div></details></section>
      <div class="account-tabs" role="tablist" aria-label="账户视图">${[['chart','前瞻观察'],['records','交易记录'],['performance','绩效']].map(([key,label])=>`<button type="button" role="tab" id="account-tab-${key}" aria-controls="account-panel-${key}" aria-selected="${tab===key}" tabindex="${tab===key?0:-1}" data-account-tab="${key}">${label}</button>`).join('')}</div>
      <section id="account-panel-chart" role="tabpanel" aria-labelledby="account-tab-chart" data-account-panel="chart" ${tab==='chart'?'':'hidden'} class="panel section account-chart" data-account-section="chart"><div class="section-head"><span class="subtle">选择截止 ${esc(a.selection_data_cutoff)} · 截止线左侧为行情背景</span><a id="expandAccountChart" class="button" target="_blank" rel="noopener" hidden>展开大图 ↗</a></div><div id="accountChartMessage" class="chart-message" hidden></div><div id="accountChartFrameHost" class="chart-frame-host"><div class="loading">正在加载前瞻观察图…</div></div></section>
      <div id="account-panel-records" role="tabpanel" aria-labelledby="account-tab-records" data-account-panel="records" ${tab==='records'?'':'hidden'}><div class="record-tabs" role="tablist" aria-label="交易记录类型">${[['intents','订单意图'],['orders','订单'],['fills','成交']].map(([key,label])=>`<button type="button" role="tab" id="record-tab-${key}" aria-controls="record-panel-${key}" aria-selected="${recordTab===key}" tabindex="${recordTab===key?0:-1}" data-record-tab="${key}">${label}</button>`).join('')}</div>
      ${accountRecords('intents','订单意图',[['决策ID',r=>r.decision_id],['计划环节',r=>planRoleLabel(r.payload?.role)],['计划时点',r=>r.payload?.checkpoint||'—'],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['委托价',r=>orderPriceLabel(r)==='市价'?'市价':formatPrice(orderPriceLabel(r))],['有效交易日',r=>r.valid_session],['状态',r=>statusLabel(r.status)],['Futu订单',r=>r.channel_order_id||'—']],intents,view)}
      ${accountRecords('orders','订单',[['账户',r=>r.account_id],['Futu订单',r=>r.channel_order_id],['下单时间',r=>formatBeijingTime(r.created_at)],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['委托价',r=>orderPriceLabel(r)==='市价'?'市价':formatPrice(orderPriceLabel(r))],['状态',r=>statusLabel(r.status)]],orders,view)}
      ${accountRecords('fills','成交',[['账户',r=>r.account_id],['成交ID',r=>displayFillId(r.fill_id),r=>r.fill_id],['时间',r=>formatBeijingTime(r.occurred_at)],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['成交价（不复权）',r=>formatPrice(r.price)]],fills,view)}</div>
      <section id="account-panel-performance" role="tabpanel" aria-labelledby="account-tab-performance" data-account-panel="performance" ${tab==='performance'?'':'hidden'} class="panel section" data-account-section="performance"><div class="section-head"><h2>日终绩效</h2><span class="subtle">截至 ${esc(m.observation_end||'暂无日终快照')}</span></div><div class="grid account-metrics">${metric('日终累计收益',pct(m.total_return))}${metric('最大回撤',pct(m.maximum_drawdown))}${metric('卡玛比率',m.calmar_ratio==null?'不可用':Number(m.calmar_ratio).toFixed(3))}${metric('盈亏比',m.win_loss_ratio==null?'不可用':Number(m.win_loss_ratio).toFixed(3))}${metric('已闭合交易',esc(m.closed_trades||0))}</div></section>
    </div></div>`;
}
function replaceAccountSections(markup,accountId){
  const current=document.querySelector('[data-account-page]');
  if(!current||current.dataset.accountId!==accountId)return false;
  const staging=document.createElement('div');staging.innerHTML=markup;
  const next=staging.firstElementChild;
  const pairs=ACCOUNT_REFRESH_SECTIONS.map(key=>[
    current.querySelector(`[data-account-section="${key}"]`),
    next.querySelector(`[data-account-section="${key}"]`),
  ]);
  if(pairs.some(([existing,fresh])=>!existing||!fresh))return false;
  pairs.forEach(([existing,fresh])=>{
    if(existing.isEqualNode(fresh))return;
    const tableScroll=existing.querySelector('.table-wrap')?.scrollLeft;
    const sidebarScroll=existing.scrollTop;
    existing.replaceWith(fresh);
    fresh.scrollTop=sidebarScroll;
    if(tableScroll!=null)fresh.querySelector('.table-wrap').scrollLeft=tableScroll;
  });
  return true;
}
function renderAccount(snapshot){
  const scope=snapshot.scope,a=snapshot.account;
  state.accountSnapshot=snapshot;
  const view=accountView(scope.account_id);
  for(const kind of ['intents','orders','fills'])view.pages[kind]=recordPage(snapshot[kind]||[],view.pages[kind]).page;
  const markup=accountMarkup(snapshot,state.accounts,accountView(scope.account_id));
  if(!replaceAccountSections(markup,scope.account_id))document.querySelector('#app').innerHTML=markup;
  bindAccountEvents(scope.account_id,a.paused);
  applyAccountView(scope.account_id);
}
async function retryAccountChart(accountId){
  const pending={scope:{account_id:accountId},status:'BUILDING',chart_url:null,fingerprint:null,message:'正在重新生成观察图'};
  applyAccountChart(pending);
  try{
    let status=await post(`/api/virtual-accounts/${encodeURIComponent(accountId)}/chart/refresh`,{});
    applyAccountChart(status);
    for(let attempt=0;attempt<45&&chartIsPending(status);attempt++){
      await new Promise(resolve=>setTimeout(resolve,1000));
      if(parseRoute(location.pathname).accountId!==accountId)return;
      status=await getJson(`/api/virtual-accounts/${encodeURIComponent(accountId)}/chart`);
      applyAccountChart(status);
    }
  }catch(error){
    applyAccountChart({scope:{account_id:accountId},status:'UNAVAILABLE',chart_url:null,fingerprint:null,message:error.message});
  }
}
function applyAccountChart(status){
  const host=document.querySelector('#accountChartFrameHost'),message=document.querySelector('#accountChartMessage');
  if(!host||status?.scope?.account_id!==parseRoute(location.pathname).accountId)return;
  message.textContent=status.message||'';message.hidden=!status.message;
  const expand=document.querySelector('#expandAccountChart');
  expand.hidden=!status.chart_url;
  if(status.chart_url)expand.href=status.chart_url;
  if(status.status==='BUILDING'){
    host.innerHTML='<div class="loading">正在生成前瞻观察图…</div>';
    state.chart={account_id:status.scope.account_id,fingerprint:null};return;
  }
  if(status.status==='UNAVAILABLE'||!status.chart_url){
    host.innerHTML=`<div class="error"><strong>前瞻观察图不可用</strong><div>${esc(status.message)}</div><button id="retryAccountChart" class="button" type="button">重新加载图表</button></div>`;
    document.querySelector('#retryAccountChart').onclick=()=>retryAccountChart(status.scope.account_id);
    state.chart={account_id:status.scope.account_id,fingerprint:null};return;
  }
  const current={account_id:status.scope.account_id,fingerprint:status.fingerprint};
  if(chartShouldReload(state.chart,status)||!document.querySelector('#accountChartFrame')){
    state.chartObserver?.disconnect();
    host.innerHTML=`<iframe id="accountChartFrame" data-account-id="${esc(status.scope.account_id)}" title="${esc(status.scope.release_id)}前瞻观察图" src="${esc(status.chart_url)}" scrolling="no"></iframe>`;
    const frame=document.querySelector('#accountChartFrame'),view=accountView(status.scope.account_id);
    frame.onload=()=>{
      if(!frame.isConnected)return;
      const doc=frame.contentDocument;
      doc.querySelector(`[data-range="${view.chartRange||'all'}"]`)?.click();
      doc.addEventListener('click',event=>{const range=event.target.closest('[data-range]');if(range)view.chartRange=range.dataset.range;});
      state.chartObserver=new ResizeObserver(()=>{
        const height=Math.ceil(doc.body.getBoundingClientRect().height);
        if(height>0&&frame.isConnected)host.style.height=`${height+2}px`;
      });
      state.chartObserver.observe(doc.body);
    };
  }
  state.chart=current;
}
function applyAccountView(accountId){
  const view=accountView(accountId);
  document.querySelectorAll('[data-account-panel]').forEach(el=>el.hidden=el.dataset.accountPanel!==view.tab);
  document.querySelectorAll('[data-record-panel]').forEach(el=>el.hidden=el.dataset.recordPanel!==view.records);
  for(const [selector,key,attribute] of [['[data-account-tab]','tab','accountTab'],['[data-record-tab]','records','recordTab']]){
    document.querySelectorAll(selector).forEach(el=>{const selected=el.dataset[attribute]===view[key];el.setAttribute('aria-selected',String(selected));el.tabIndex=selected?0:-1;});
  }
}
function bindAccountEvents(accountId,paused){
  const view=accountView(accountId);
  document.querySelectorAll('[data-account]').forEach(el=>el.onclick=()=>navigate(`/accounts/${encodeURIComponent(el.dataset.account)}`));
  document.querySelector('#accountPicker').onchange=event=>navigate(`/accounts/${encodeURIComponent(event.target.value)}`);
  document.querySelector('[data-account-audit]').onclick=event=>{event.preventDefault();navigate(event.currentTarget.getAttribute('href'));};
  document.querySelectorAll('[data-account-details]').forEach(el=>el.ontoggle=()=>{if(el.isConnected)view[el.dataset.accountDetails]=el.open;});
  for(const [selector,key,attribute] of [['[data-account-tab]','tab','accountTab'],['[data-record-tab]','records','recordTab']]){
    const buttons=[...document.querySelectorAll(selector)];
    buttons.forEach((el,index)=>{
      el.onclick=()=>{view[key]=el.dataset[attribute];applyAccountView(accountId);};
      el.onkeydown=event=>{
        const next={ArrowRight:(index+1)%buttons.length,ArrowLeft:(index+buttons.length-1)%buttons.length,Home:0,End:buttons.length-1}[event.key];
        if(next==null)return;event.preventDefault();buttons[next].click();buttons[next].focus();
      };
    });
  }
  document.querySelectorAll('[data-record-page]').forEach(el=>el.onclick=()=>{view.pages[el.dataset.recordKind]=Number(el.dataset.recordPage);renderAccount(state.accountSnapshot);});
  document.querySelector('#accountSwitch').onclick=async()=>{try{await post(`/api/virtual-accounts/${encodeURIComponent(accountId)}/${paused?'resume':'pause'}`);toast(paused?'账户已恢复':'账户已暂停');await loadRoute({showLoading:false});}catch(e){toast(e.message);}};
  document.querySelectorAll('[data-ack-intent]').forEach(el=>el.onclick=async()=>{const note=prompt('请填写复核结论。确认后账户才会恢复自动交易：');if(!note?.trim())return;try{await post(`/api/virtual-accounts/${encodeURIComponent(accountId)}/intents/${encodeURIComponent(el.dataset.ackIntent)}/acknowledge`,{resolution_note:note.trim()});toast('执行缺口已确认');await loadRoute({showLoading:false});}catch(e){toast(e.message);}});
}

export function channelMarkup(s,detailsOpen=false){
  const cashAvailable=s.cash_difference!=null,cashOk=cashAvailable&&Math.abs(Number(s.cash_difference))<=.01;
  const assetAvailable=s.asset_difference!=null,assetOk=assetAvailable&&Math.abs(Number(s.asset_difference))<=.01;
  const cashState=cashAvailable?(cashOk?'资金对账正常':'资金对账异常'):'资金数据不可用';
  const assetState=assetAvailable?(assetOk?'估值一致':'估值口径不同'):'估值数据不可用';
  return `<div class="workspace"><section class="panel hero"><div><div class="eyebrow">执行渠道 · FUTU 模拟盘 CN</div><h1>Futu 模拟盘 CN 渠道</h1><div class="subtle">底层模拟账户 · 对账 ${statusLabel(s.reconciliation_status)} · 最近对账 ${esc(formatBeijingTime(s.last_reconcile_at))}</div></div><button id="channelSwitch" class="switch ${s.paused?'paused':''}" role="switch" aria-checked="${!s.paused}">${s.paused?'渠道已暂停 · 点击恢复':'渠道自动运行 · 点击暂停'}</button></section>${alerts((s.alerts||[]).map(x=>({message:statusLabel(x)})))}<div class="grid channel-core-metrics">${metric('Futu总资产',money(s.account?.total_assets))}${metric('可用现金',money(s.account?.cash))}${metric('已分配额度',money(s.strategy_allocated_capital))}${metric('未分配额度',money(s.unallocated_capital))}</div><section class="panel reconciliation-summary"><details id="channelReconciliationDetails" class="reconciliation-details"${detailsOpen?' open':''}><summary class="reconciliation-bar"><div class="reconciliation-state ${cashOk?'ok':'warning'}"><strong>${cashState}</strong><span>现金差异 ${money(s.cash_difference)}</span></div><div class="reconciliation-state ${assetOk?'ok':'neutral'}"><strong>${assetState}</strong><span>Futu−PTE ${money(s.asset_difference)}</span></div><span class="reconciliation-trigger">查看明细</span></summary><div class="reconciliation-detail-grid"><div><span>Futu持仓市值</span><strong>${money(s.account?.market_value)}</strong></div><div><span>PTE账务现金</span><strong>${money(s.logical_cash)}</strong></div><div><span>PTE日终总资产</span><strong>${money(s.logical_total_assets)}</strong></div><div><span>Futu−PTE估值差异</span><strong>${money(s.asset_difference)}</strong></div><div><span>平账账户余额</span><strong>${money(s.reconciliation_account?.cash)}</strong></div></div><p>Futu按当前行情实时估值；PTE账务总资产按各虚拟账户最近日终数据估值。</p></details></section><section class="panel section"><div class="section-head"><h2>策略承载账户</h2><span class="badge">${(s.accounts||[]).length} 个账户</span></div>${rowsTable([['虚拟账户',r=>r.name],['账户ID',r=>r.account_id],['策略版本',r=>r.release_id],['交易标的',r=>r.symbol],['分配额度',r=>money(r.initial_cash)],['可用现金',r=>money(r.cash)],['冻结资金',r=>money(r.frozen_cash)],['持仓',r=>formatQuantity(r.quantity)],['状态',accountOperatingStatus]],s.accounts)}</section><section id="channelOrders" class="panel section"><div class="section-head"><h2>订单</h2><span class="badge">逐笔归属</span></div>${rowsTable([['时间',r=>formatBeijingTime(r.created_at)],['Futu订单',r=>r.channel_order_id],['虚拟账户',r=>channelOrderAccountLabel(r)],['决策ID',r=>r.decision_id||'历史未记录'],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['委托价',r=>orderPriceLabel(r)==='市价'?'市价':formatPrice(orderPriceLabel(r))],['状态',r=>statusLabel(r.status)],['操作',r=>['SUBMITTED','FILLED_PART'].includes(r.status)?'二次确认撤单':'—']],s.orders)}</section><section class="panel section"><div class="section-head"><h2>成交</h2><span class="badge">Futu回报</span></div>${rowsTable([['时间',r=>formatBeijingTime(r.occurred_at)],['虚拟账户',r=>channelOrderAccountLabel(r)],['成交ID',r=>displayFillId(r.fill_id),r=>r.fill_id],['Futu订单',r=>r.order_id],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['价格',r=>formatPrice(r.price)],['费用',r=>money(r.fee)]],s.fills)}</section></div>`;
}
function renderChannel(s){const detailsOpen=document.querySelector('#channelReconciliationDetails')?.open||false;document.querySelector('#app').innerHTML=channelMarkup(s,detailsOpen);document.querySelector('#channelSwitch').onclick=async()=>{try{await post(`/api/channels/futu-simulate-cn/${s.paused?'resume':'pause'}`);toast(s.paused?'渠道已恢复':'渠道已暂停');await loadRoute({showLoading:false});}catch(e){toast(e.message);}};document.querySelectorAll('#channelOrders tbody tr').forEach((tr,i)=>{const o=s.orders?.[i];if(o&&['SUBMITTED','FILLED_PART'].includes(o.status))tr.onclick=()=>cancelOrder(o);});}
async function cancelOrder(order){if(!confirm(`确认申请撤销Futu订单？\n订单 ${order.channel_order_id}\n${sideLabel(order.side)} ${formatQuantity(order.quantity)}\n虚拟账户 ${channelOrderAccountLabel(order)}`))return;try{const body={account_id:order.account_id,channel_order_id:order.channel_order_id};const {token}=await post('/api/channels/futu-simulate-cn/cancel-token',body);if(!confirm('撤单令牌已签发，有效期2分钟。再次确认撤单。'))return;await post('/api/channels/futu-simulate-cn/cancel',{...body,token});toast('撤单请求已提交');await loadRoute({showLoading:false});}catch(e){toast(e.message);}}

function renderComparison(s){document.querySelector('#app').innerHTML=`<section class="panel hero"><div><div class="eyebrow">只读评估</div><h1>虚拟账户比较</h1><div class="subtle">各账户按自身前瞻观察窗口统计，指标与账户详情页保持一致</div></div></section><section class="panel section"><div class="section-head"><h2>参与账户</h2><span class="badge">无交易干预</span></div><div class="comparison-select">${state.accounts.map(a=>`<label><input type="checkbox" value="${esc(a.account_id)}" ${s.accounts.some(x=>x.account_id===a.account_id)?'checked':''}> ${esc(a.name)} · ${esc(a.release_id)}</label>`).join('')}</div></section><section class="panel section"><div class="section-head"><h2>核心指标</h2><span class="badge">OPC优先级</span></div>${rowsTable([['账户',r=>r.account_id],['策略发布',r=>r.release_id],['观察窗口',r=>r.metrics.observation_start&&r.metrics.observation_end?`${r.metrics.observation_start} 至 ${r.metrics.observation_end}`:'尚无日终快照'],['交易日',r=>r.metrics.observation_count??0],['闭合交易',r=>r.metrics.closed_trades??0],['累计收益',r=>pct(r.metrics.total_return)],['最大回撤',r=>pct(r.metrics.maximum_drawdown)],['卡玛比率',r=>r.metrics.calmar_ratio==null?'不可用':Number(r.metrics.calmar_ratio).toFixed(3)],['盈亏比',r=>r.metrics.win_loss_ratio==null?'不可用':Number(r.metrics.win_loss_ratio).toFixed(3)]],s.accounts)}</section>`;document.querySelectorAll('.comparison-select input').forEach(el=>el.onchange=()=>{const ids=[...document.querySelectorAll('.comparison-select input:checked')].map(x=>x.value);navigate(`/comparison${ids.length?'?'+comparisonQuery(ids):''}`);});}

function renderAudit(s){
  const selected=new URLSearchParams(location.search),categories=['STRATEGY','TRADING','SYSTEM','OTHER'];
  const cards=categories.map(category=>`<button class="panel metric audit-category" data-category="${category}"><label>${auditCategoryLabel(category)}</label><strong>${s.category_counts?.[category]||0}</strong></button>`).join('');
  const options=categories.map(category=>`<option value="${category}" ${selected.get('category')===category?'selected':''}>${auditCategoryLabel(category)}</option>`).join('');
  const events=(s.events||[]).length?(s.events||[]).map(event=>`<article class="event audit-event"><div class="event-title"><div><span class="badge">${esc(auditCategoryLabel(event.category))}</span> <strong>${esc(auditEventLabel(event.event_type))}</strong></div><time>${esc(formatBeijingTime(event.occurred_at))}</time></div><div class="audit-scope"><span>归属</span><strong>${esc(auditScopeLabel(event,state.accounts))}</strong></div><div class="audit-meta"><span>级别 ${esc(auditSeverityLabel(event.severity))}</span><span>结果 ${esc(auditOutcomeLabel(event.outcome))}</span>${event.strategy_id?`<span>策略 ${esc(event.strategy_id)}${event.strategy_version?` · 版本 ${esc(event.strategy_version)}`:''}</span>`:''}${event.channel==='futu_simulate_cn'?'<span>执行渠道 Futu模拟盘CN渠道</span>':''}</div>${event.correlation_id?`<button class="link-button" data-correlation="${esc(event.correlation_id)}">关联 ${esc(event.correlation_id)}</button>`:''}${renderEventDetails(event.details)}</article>`).join(''):'<div class="empty">当前筛选条件下暂无事件</div>';
  document.querySelector('#app').innerHTML=`<section class="panel hero"><div><div class="eyebrow">PTE · 只读审计账本</div><h1>运行事件</h1><div class="subtle">事件以 UTC 持久化，页面统一显示北京时间 · 最近同步 ${esc(formatBeijingTime(s.as_of))}</div></div></section><div class="grid audit-summary">${cards}</div><section class="panel section"><form id="auditFilters" class="audit-filters"><label>类别<select name="category"><option value="">全部类别</option>${options}</select></label><label>账户<input name="account_id" value="${esc(selected.get('account_id')||'')}" placeholder="账户ID"></label><label>策略<input name="strategy_id" value="${esc(selected.get('strategy_id')||'')}" placeholder="策略ID"></label><label>渠道<input name="channel" value="${esc(selected.get('channel')||'')}" placeholder="如 futu_simulate_cn"></label><label>关联ID<input name="correlation_id" value="${esc(selected.get('correlation_id')||'')}" placeholder="决策或发布链路"></label><button class="button" type="submit">筛选</button><button class="button secondary" id="clearAuditFilters" type="button">清空</button></form></section><section class="panel section"><div class="section-head"><h2>事件明细</h2><span class="badge">${(s.events||[]).length} 条</span></div><div class="audit-list">${events}</div>${s.next_before_id?'<button id="moreAudit" class="button secondary" type="button">查看更早事件</button>':''}</section>`;
  document.querySelectorAll('[data-category]').forEach(el=>el.onclick=()=>{const params=new URLSearchParams(location.search);params.set('category',el.dataset.category);navigate(`/audit-events?${params}`);});
  document.querySelectorAll('[data-correlation]').forEach(el=>el.onclick=()=>navigate(`/audit-events?${auditQuery({correlation_id:el.dataset.correlation})}`));
  document.querySelector('#auditFilters').onsubmit=event=>{event.preventDefault();const query=auditQuery(Object.fromEntries(new FormData(event.currentTarget)));navigate(`/audit-events${query?'?'+query:''}`);};
  document.querySelector('#clearAuditFilters').onclick=()=>navigate('/audit-events');
  const more=document.querySelector('#moreAudit');if(more)more.onclick=()=>{const params=new URLSearchParams(location.search);params.set('before_id',s.next_before_id);navigate(`/audit-events?${params}`);};
}

async function loadAccounts(options={}){const payload=await getJson('/api/virtual-accounts',options);state.accounts=payload.accounts||[];return payload;}
async function loadRoute({showLoading=true,forceRender=false}={}){
  const route=parseRoute(location.pathname);setNav(route.page);
  let scope=route.page==='account'?route.accountId:`${route.page}${location.search}`;
  const request=state.loader.begin(scope);
  try{
    if(showLoading)document.querySelector('#app').innerHTML='<div class="loading">正在加载当前作用域…</div>';
    const accountIndex=await loadAccounts({signal:request.signal});
    if(route.page==='account'){
      const requested=route.accountId||localStorage.getItem('pte.lastAccountId');
      const id=chooseAccountId(requested,state.accounts,accountIndex.default_account_id);
      if(!id){
        document.querySelector('#app').innerHTML='<section class="panel"><h1>虚拟账户</h1><p>暂无可展示的虚拟账户。</p></section>';
        document.querySelector('#pollWarning').hidden=true;
        localStorage.removeItem('pte.lastAccountId');
        if(route.accountId)history.replaceState({},'','/accounts/');
        state.renderedScope=null;state.fingerprint=null;state.chart=null;
        return;
      }
      if(route.accountId!==id){navigate(`/accounts/${encodeURIComponent(id)}`,true);return;}
    }
    scope=route.page==='account'?route.accountId:`${route.page}${location.search}`;
    let snapshot,chartPromise=null;
    if(route.page==='account'){
      chartPromise=getJson(`/api/virtual-accounts/${encodeURIComponent(route.accountId)}/chart`,{signal:request.signal}).catch(error=>({scope:{account_id:route.accountId},status:'UNAVAILABLE',chart_url:null,fingerprint:null,message:error.message}));
      snapshot=await getJson(`/api/virtual-accounts/${encodeURIComponent(route.accountId)}/snapshot`,{signal:request.signal});
    }
    else if(route.page==='channel')snapshot=await getJson('/api/channels/futu-simulate-cn/snapshot',{signal:request.signal});
    else if(route.page==='comparison'){const ids=new URLSearchParams(location.search).getAll('account_id');snapshot=await getJson(`/api/comparison${ids.length?'?'+comparisonQuery(ids):''}`,{signal:request.signal});}
    else snapshot=await getJson(`/api/audit-events${location.search}`,{signal:request.signal});
    if(!state.loader.accept(request,scope))return;
    if(route.page==='account'&&snapshot.scope.account_id!==route.accountId)throw new Error('服务端账户作用域不一致');
    const fingerprint=snapshotFingerprint({accounts:state.accounts,snapshot});
    if(forceRender||scope!==state.renderedScope||fingerprint!==state.fingerprint){
      if(route.page==='account'){localStorage.setItem('pte.lastAccountId',route.accountId);renderAccount(snapshot);}
      else if(route.page==='channel')renderChannel(snapshot);else if(route.page==='comparison')renderComparison(snapshot);else renderAudit(snapshot);
      state.renderedScope=scope;state.fingerprint=fingerprint;
    }
    if(route.page==='account'){
      const chartStatus=await chartPromise;
      if(!state.loader.accept(request,scope)||chartStatus.scope.account_id!==route.accountId)return;
      applyAccountChart(chartStatus);
    }
    state.lastSuccess=new Date();
    const warning=document.querySelector('#pollWarning');warning.hidden=true;warning.textContent='';
  }catch(error){
    if(error.name==='AbortError')return;
    const message=`刷新失败：${error.message} · 继续显示最后成功数据`;
    const warning=document.querySelector('#pollWarning');warning.hidden=false;warning.textContent=message;
    if(showLoading||state.renderedScope!==scope)document.querySelector('#app').innerHTML=`<div class="error"><strong>当前作用域加载失败</strong><div>${esc(error.message)}</div><div class="subtle">最后成功 ${state.lastSuccess?state.lastSuccess.toLocaleString():'无'}</div></div>`;
  }
}
function navigate(url,replace=false){if(url!==`${location.pathname}${location.search}`)history[replace?'replaceState':'pushState']({},'',url);loadRoute(navigationOptions(state.renderedScope));}
function boot(){document.querySelectorAll('a[href^="/"]').forEach(a=>a.onclick=e=>{e.preventDefault();navigate(a.getAttribute('href'));});document.querySelector('#systemStatus').onclick=openSystemEvents;document.querySelector('#closeSystemEvents').onclick=()=>document.querySelector('#systemEventsDialog').close();window.addEventListener('popstate',()=>loadRoute(navigationOptions(state.renderedScope)));refreshSystem();loadRoute({showLoading:true,forceRender:true});setInterval(refreshSystem,10000);setInterval(()=>loadRoute({showLoading:false}),5000);}
if(typeof document!=='undefined')boot();
