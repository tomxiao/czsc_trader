import {captureView, restoreView, updateView, reserveViewport} from './view_state.js';

export function parseRoute(pathname) {
  const account = pathname.match(/^\/accounts\/([^/]+)$/);
  if (account) return {page: 'account', accountId: decodeURIComponent(account[1])};
  if (pathname === '/channels/futu-simulate-cn') return {page: 'channel', channel: 'futu_simulate_cn'};
  if (pathname === '/channels') return {page: 'channel'};
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
export const comparisonQuery = ids => ids.length ? ids.map(id=>`account_id=${encodeURIComponent(id)}`).join('&') : 'account_id=';
export const auditQuery = filters => {
  const query=new URLSearchParams();
  Object.entries(filters||{}).forEach(([key,value])=>{if(value!=null&&value!=='')query.set(key,value);});
  return query.toString();
};
export const auditCategoryLabel = value => ({STRATEGY:'策略事件',TRADING:'交易事件',SYSTEM:'系统事件',OTHER:'其他事件'}[value]||value||'未分类');
export const auditEventLabel = value => ({
  ACCOUNT_RETIRED:'账户退出并回收资金',
  MARKET_DATA_PUBLICATION_REQUESTED:'请求发布数据',MARKET_DATA_PUBLISHED:'发布数据成功',MARKET_DATA_PUBLICATION_FAILED:'发布数据失败',MARKET_DATA_OBSERVED:'验收SRT数据',MARKET_DATA_OBSERVATION_FAILED:'SRT数据验收失败',DECISION_GENERATED:'生成决策',DECISION_GENERATION_FAILED:'生成决策失败',ACCOUNT_DECISION_DRIVEN:'人工驱动账户决策',ACCOUNT_DECISION_DRIVE_FAILED:'人工驱动账户决策失败',DECISION_SUPERSEDED:'决策已被替代',SIGNAL_TRIGGERED:'触发信号',SIGNAL_CLEARED:'信号解除',DECISION_EXPIRED:'决策过期',CHANNEL_STRATEGY_BOUND:'历史关系 · 渠道曾直接绑定策略',ACCOUNT_STRATEGY_BOUND:'虚拟账户绑定策略',ACCOUNT_STRATEGY_NAME_UPDATED:'更新策略名称',ACCOUNT_DISPLAY_NAME_UPDATED:'更新账户显示名',ACCOUNT_CHANNEL_BOUND:'虚拟账户绑定渠道',CHANNEL_RECONCILIATION_FAILED:'渠道对账失败',CHANNEL_RECONCILIATION_RECOVERED:'渠道对账恢复',
  EXECUTION_GAP_ACKNOWLEDGED:'已确认执行缺口',EXECUTION_PLAN_LEG_SKIPPED:'计划环节未触发',EXECUTION_PLAN_LEG_READY:'计划环节就绪',EXECUTION_PLAN_BLOCKED:'执行计划阻塞',ORDER_INTENT_CREATED:'创建订单意图',ORDER_INTENT_RECOVERED:'恢复订单意图',ORDER_SUBMISSION_BLOCKED:'订单提交受阻',ORDER_SUBMITTED:'订单已提交',ORDER_SUBMISSION_FAILED:'订单提交失败',ORDER_REJECTED:'订单被明确拒绝',CANCEL_REQUESTED:'请求撤单',CANCEL_SUCCEEDED:'撤单成功',CANCEL_FAILED:'撤单失败',ORDER_PARTIALLY_FILLED:'订单部分成交',ORDER_FILLED:'订单成交',ORDER_TERMINATED:'订单终止',BROKER_FEE_RECONCILED:'Futu费用对账',
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
  if(event?.channel==='futu_US_sim_channel')return 'Futu 美股模拟渠道';
  if(event?.category==='SYSTEM')return event.channel_account_id||'PTE 系统';
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
  const visible=accounts.filter(item=>item.run_state!=='RETIRED');
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
function closedWinLossRatio(metrics){
  if(metrics.win_loss_ratio!=null)return Number(metrics.win_loss_ratio).toFixed(3);
  return ({NO_CLOSED_TRADES:'无闭合交易',NO_WINS:'无盈利交易',NO_LOSSES:'无亏损交易'})[metrics.win_loss_ratio_status]||'不可用';
}
const shortHash = value => value?String(value).slice(0,10):'—';
export const actionLabel = value => ({BUY:'买入',SELL:'卖出',ROTATE:'日内轮换',WAIT:'等待',HOLD:'持有'}[value]||value||'等待');
export const statusLabel = value => ({READY:'就绪',PAUSED:'已暂停',RETIRED:'已退出',EXECUTING:'执行中',COMPLETED:'已完成',CANCELLED:'已取消',INCOMPLETE:'未完成',RUNNING:'运行中',OK:'正常',CONNECTED:'已连接',DEGRADED:'降级',PAPER_READY:'获准模拟交易',LIVE_READY:'获准实盘交易',BLOCKED:'阻塞',UNAVAILABLE:'不可用',ACCOUNT_CHART_UNAVAILABLE:'前瞻观察图不可用',CHANNEL_UNAVAILABLE:'Futu不可用',CHANNEL_CASH_MISMATCH:'PTE账务现金与Futu现金不一致',CHANNEL_RECONCILIATION_BLOCKED:'渠道对账阻塞',FUTU_CASH_RECONCILIATION_UNATTRIBUTED:'Futu现金差异来源不明',FUTU_CASH_RECONCILIATION_OUT_OF_RANGE:'Futu费用差异超出允许范围',FUTU_CASH_RECONCILIATION_AMBIGUOUS:'Futu现金差异无法安全归属',VIRTUAL_ACCOUNT_BLOCKED:'虚拟账户阻塞',ORDER_SUBMISSION_UNRESOLVED:'存在下单结果待确认',DATA_PUBLICATION_FAILED:'发布数据失败',DATA_PUBLICATION_OVERDUE:'数据发布超期',PUBLICATION_CALENDAR_UNAVAILABLE:'发布所需交易日历不可用',DECISION_GENERATION_OVERDUE:'决策生成超期',SCHEDULER_STALLED:'调度器停滞',SCHEDULER_OPERATION_FAILED:'调度任务失败',SKIPPED_DEPENDENCY:'依赖条件未触发',WAITING_DEPENDENCY:'等待前序成交及计划时点',PENDING_SUBMIT:'待提交',SUBMITTING:'提交中',SUBMISSION_UNCERTAIN:'提交结果待确认',SUBMISSION_FAILED:'提交失败',SUPERSEDED:'已被新决策替代',REJECTED:'已拒绝',EXPIRED:'已过期',TIMEOUT:'结果未知',SUBMITTED:'已提交',FILLED_PART:'部分成交',FILLED_ALL:'全部成交',CANCELLING_ALL:'撤单中',SUBMIT_FAILED:'提交失败',CANCELLED_PART:'部分成交后撤单',CANCELLED_ALL:'已撤销',FAILED:'失败',DISABLED:'已失效',DELETED:'已删除',FILL_CANCELLED:'成交已撤销',PENDING:'待执行'}[value]||value||'—');
export function accountOperatingStatus(account){
  const runLabel={RUNNING:'运行中',PAUSED:'已暂停',RETIRED:'已退出'}[account.run_state]||'运行状态异常';
  if(!['OK','BLOCKED'].includes(account.health))return `${runLabel} · 健康状态异常`;
  if(account.health==='BLOCKED')return `${runLabel} · 阻塞`;
  return account.run_state==='RUNNING'?`${runLabel} · 正常`:runLabel;
}
export function decisionExecutionLabel(decision){
  if(!decision?.decision_id)return '等待生成决策';
  const effect=decision.execution_effect;
  if(effect?.availability!=='AVAILABLE')return '执行效果不可用';
  if(effect.status==='COMPLETED')return effect.planning_status==='NO_CHANGE'?'本次无需调整':'本次订单已完成';
  if(effect.status==='NOT_EXECUTED'&&effect.planning_status==='BLOCKED')return '本次规划受阻';
  if(effect.status==='NOT_EXECUTED'&&effect.planning_status==='SUPPRESSED')return '观察不足，未规划';
  return {WAITING:'等待执行',PARTIAL:'部分执行',NOT_EXECUTED:'未执行',UNKNOWN:'执行结果待确认'}[effect.status]||'执行效果不可用';
}
function decisionPlanActionLabel(decision){
  const action=decision.action,label=actionLabel(action),effect=decision.execution_effect;
  if(!['BUY','SELL'].includes(action)||effect?.availability!=='AVAILABLE')return label;
  const quantity=(effect.orders||[]).reduce((total,order)=>order.side===action?total+order.quantity:total,0);
  return quantity?`${label} ${formatQuantity(quantity)}`:label;
}
const planningLabel=value=>({READY:'可执行',CONSTRAINED:'受约束执行',BLOCKED:'规划受阻',NO_CHANGE:'无需调整',SUPPRESSED:'观察不足，未规划'}[value]||value||'—');
const executionReasonLabel=value=>({INSUFFICIENT_CASH:'可用资金不足',BELOW_MINIMUM_UNIT:'不足最小交易单位',BELOW_PRICE_TICK:'不足最小报价单位',INSUFFICIENT_SELLABLE_QUANTITY:'可卖数量不足',ORDER_QUANTITY_LIMIT:'订单数量限制',DEPENDENCY_UNAVAILABLE:'依赖条件不可执行',NORMAL_UNFILLED:'限价单正常结束，未成交',NORMAL_PARTIAL:'部分成交，剩余委托按计划结束',ORDER_REJECTED:'渠道明确拒单，本次未成交',EXECUTION_CONSTRAINED:'资金或可卖数量不足，本次未执行',EXECUTION_EXPIRED:'本地委托未提交，执行窗口已结束',DEPENDENCY_NOT_TRIGGERED:'前序条件未触发'}[value]||value);
export function executionEffectMarkup(decision,currency='CNY'){
  if(!decision?.decision_id)return '<p class="subtle">等待生成决策</p>';
  const effect=decision.execution_effect;
  if(effect?.availability!=='AVAILABLE')return `<h3>执行效果不可用</h3><p class="subtle">${esc(effect?.message||'缺少执行效果证据，不能从旧决策状态推断目标是否达成。')}</p>`;
  const reasons=[...new Set([...(effect.constraint_reasons||[]),...(effect.orders||[]).map(order=>order.reason).filter(Boolean)])];
  const deviation=effect.weight_deviation==null?'不可用':`${(effect.weight_deviation*100).toFixed(2)} 个百分点`;
  return `<h3>当前执行效果</h3><p class="subtle">当前确认账户与本次决策目标对照，不是历史账户重建。按本次决策的不复权参考价估值，不代表实时行情。</p>${detailFacts([
    ['执行结果',decisionExecutionLabel(decision)],['订单执行进度',effect.status==='UNKNOWN'?'结果待确认':effect.terminal?'本次执行已结束':'仍有订单待完成'],
    ['目标仓位',pct(effect.target_weight)],['实际仓位',effect.actual_weight==null?'不可用（账户净值为零）':pct(effect.actual_weight)],['偏差（实际－目标）',deviation],
    ['规划结果',planningLabel(effect.planning_status)],['约束／未完成原因',reasons.length?reasons.map(executionReasonLabel).join('；'):'未记录'],
    ['期望持股',formatQuantity(effect.desired_quantity)],['可执行目标持股',formatQuantity(effect.planned_quantity)],['当前确认持股',formatQuantity(effect.actual_quantity)],
    ['估值参考价（不复权）',`${formatPrice(effect.valuation_price)} ${currency}`],['参考价观测时点',formatBeijingTime(effect.valuation_at)],['账户效果查询时点',formatBeijingTime(effect.as_of)],
    ['现金（含冻结）',`${money(effect.cash)} ${currency}`],['可用现金',`${money(effect.available_cash)} ${currency}`],['应收',`${money(effect.receivable)} ${currency}`],['本口径账户净值',`${money(effect.equity)} ${currency}`],
  ])}<p class="subtle">本次订单完成仅表示可执行订单计划完成，不代表目标仓位完全达成。</p>`;
}
export function decisionDetailsMarkup(decision,currency='CNY'){
  const d=decision||{},explanation=d.strategy_output?.explanation;
  return detailFacts([
    ['决策 ID',d.decision_id],['策略判断',explanation?.judgment],['执行计划',d.decision_id?decisionPlanActionLabel(d):'暂无决策'],
    ['决策流程状态',d.status==='COMPLETED'?'流程结束':d.status&&statusLabel(d.status)],
    ['信号日期',d.signal_date],['有效交易日',d.valid_session],
    ['依据',explanation?.basis?.map(item=>item.text).join('；')],['后续观察',explanation?.next_watch],
  ])+executionEffectMarkup(d,currency);
}
const DECISION_INPUT_REASON_TEMPLATES=new Map([
  ['INCOMPLETE_DATA:OHLCV observations omit expected trading sessions','{instrument}缺少 {period} 的行情'],
  ['INCOMPLETE_DATA:equity bars differ from the independent session grid','{instrument}行情与交易日历不一致'],
]);
function eventReason(detail){
  const reason=detail.message||detail.error||detail.reason;
  const prefix='forward V4 input preparation is incomplete: ';
  if(typeof reason!=='string'||!reason.startsWith(prefix))return reason;
  const errors=reason.slice(prefix.length).split(/; (?=DataError\()/);
  const causes=errors.map(error=>{
    // Persisted scheduler events carry the data error as text.
    const [,code,message]=error.match(/^DataError\(code='([^']+)', message='([^']+)'/)||[];
    const template=DECISION_INPUT_REASON_TEMPLATES.get(`${code}:${message}`);
    if(!template)return error;
    const symbol=error.match(/'symbol': '([^']+)'/)?.[1];
    const dates=error.match(/'missing_dates': \[([^\]]*)\]/)?.[1].match(/\b\d{4}-\d{2}-\d{2}\b/g)||[];
    const firstDates=dates.slice(0,3).join('、');
    const fields={
      instrument:symbol?`${symbol} `:'',
      period:dates.length>3?`${firstDates} 等 ${dates.length} 个交易日`:firstDates||'部分交易日',
    };
    return template.replace(/\{(instrument|period)\}/g,(_,field)=>fields[field]);
  });
  return causes.some((cause,index)=>cause!==errors[index])?`本周期决策未生成。${causes.join('；')}。`:reason;
}
export function auditSummary(event){
  const detail=event?.details||event?.payload||{};
  if(detail.termination_reason==='NORMAL_UNFILLED')return '限价买单正常结束，零成交';
  if(detail.reason==='DEPENDENCY_NOT_TRIGGERED')return '前序买单正常零成交，跳过依赖卖单';
  if(['ORDER_FILLED','ORDER_PARTIALLY_FILLED'].includes(event?.event_type))return `${sideLabel(detail.side)} ${formatQuantity(detail.quantity)}，成交均价 ${formatPrice(detail.average_fill_price)}`;
  if(event?.event_type==='ORDER_SUBMITTED')return `${sideLabel(detail.side)} ${formatQuantity(detail.quantity)}，${String(detail.order_type||'LIMIT').toUpperCase()==='MARKET'?'市价单':`限价 ${formatPrice(detail.limit_price)}`}`;
  if(event?.event_type==='DECISION_GENERATED')return `${actionLabel(detail.action)}，目标持仓 ${formatQuantity(detail.target_quantity)}`;
  if(event?.event_type==='SIGNAL_TRIGGERED')return `${sideLabel(detail.side)} ${formatQuantity(detail.quantity)}`;
  if(event?.event_type==='BROKER_FEE_RECONCILED')return `估算费用 ${money(detail.modeled_fee)}，Futu实际费用 ${money(detail.actual_fee)}，账务调整 ${money(detail.adjustment)}`;
  if(event?.event_type==='EXTERNAL_CALL_SUCCEEDED')return `${detail.service||'外部服务'} · ${detail.operation||'调用'}成功`;
  if(event?.event_type==='EXTERNAL_CALL_FAILED')return `${detail.service||'外部服务'} · ${detail.operation||'调用'}失败`;
  const reason=eventReason(detail);
  return typeof reason==='string'?reason:auditOutcomeLabel(event?.outcome);
}
const state = {accounts:[],loader:new ScopedLoader(),lastSuccess:null,renderedScope:null,fingerprint:null,system:null,systemFingerprint:null,chart:null,navigation:null};
const marketLabels = {CN:'A 股',US:'美股'};
const validMarket = value => value==='CN'||value==='US';
const marketName = market => marketLabels[market] || 'A 股';
const scoped = (path, market) => {
  const [pathname,query='']=path.split('?');
  const params=new URLSearchParams(query);
  params.set('market',market);
  return pathname+'?'+params.toString();
};
const requestedMarket = () => {
  const explicit=new URLSearchParams(location.search).get('market');
  if(validMarket(explicit))return explicit;
  if(location.pathname==='/channels/futu-simulate-cn')return 'CN';
  const saved=localStorage.getItem('pte.market');
  return validMarket(saved)?saved:'CN';
};

async function getJson(url, options={}) {
  const response=await fetch(url,options);let payload={};
  if(url.split('?')[0]==='/api/system/status'&&response.ok){
    const loaded=document.querySelector('meta[name="pte-ui-revision"]')?.content;
    const current=response.headers.get('X-PTE-UI-Revision');
    const notice=document.querySelector('#uiUpdateNotice');
    if(notice&&loaded)notice.hidden=current===loaded;
  }
  try{payload=await response.json();}catch{payload={error:`HTTP ${response.status}`};}
  if(!response.ok)throw new Error(payload.error||`HTTP ${response.status}`);return payload;
}
function post(url,body={}){return getJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
function toast(message){const el=document.querySelector('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2200);}
function setNav(page){document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav===page));}

function detailFacts(fields){return `<dl class="detail-facts">${fields.filter(([,value])=>value!=null&&value!=='').map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`;}
function renderEventDetails(payload){return `<details class="raw-event"><summary>原始事件字段</summary><pre>${esc(JSON.stringify(payload||{},null,2))}</pre></details>`;}
function eventTitle(event){
  const detail=event.details||event.payload||{};
  if(detail.termination_reason==='NORMAL_UNFILLED')return '限价买单到期，确认零成交';
  if(event.event_type==='ORDER_SUBMISSION_FAILED'&&(event.outcome==='UNKNOWN'||detail.status==='SUBMISSION_UNCERTAIN'))return '订单提交结果未知';
  if(event.event_type==='MARKET_DATA_PREPARED')return '策略数据已准备';
  if(event.event_type==='DATA_PREPARATION_OBSERVATION_FAILED')return '策略数据准备未完成';
  return auditEventLabel(event.event_type);
}
function openDetail(title, content, trigger){
  const dialog=document.querySelector('#systemEventsDialog');
  document.querySelector('#systemEventsTitle').textContent=title;
  document.querySelector('#systemEventsContent').innerHTML=content;
  if(!dialog.open){
    state.detailTrigger=trigger;
    state.detailScroll=window.scrollY;
    dialog.showModal();
  }
  document.querySelector('#systemEventsContent').scrollTop=0;
  document.querySelector('#closeSystemEvents').focus({preventScroll:true});
}
function showAuditDetail(event,trigger){
  const details=event.details||event.payload||{};
  openDetail('事件详情',`<div class="detail-heading"><span class="event-severity" data-severity="${esc(event.severity)}">${esc(auditSeverityLabel(event.severity))}</span><h3>${esc(eventTitle(event))}</h3><p>${esc(auditSummary(event))}</p></div>`
    +detailFacts([['状态',auditOutcomeLabel(event.outcome)],['影响对象',auditScopeLabel(event,state.accounts)],
      ['时间（北京）',formatBeijingTime(event.occurred_at||event.created_at)],['原因',eventReason(details)],
      ['渠道账户',event.channel_account_id],['决策 ID',event.decision_id],['订单 ID',event.order_id],['事件 ID',event.event_id]])
    +(event.correlation_id?`<button class="button secondary" data-detail-correlation="${esc(event.correlation_id)}">查看关联事件</button>`:'')
    +renderEventDetails(event),trigger);
  const link=document.querySelector('[data-detail-correlation]');
  if(link)link.onclick=()=>{document.querySelector('#systemEventsDialog').close();navigate(`/audit-events?${auditQuery({correlation_id:event.correlation_id})}`);};
}
function eventRow(event){
  const time=event.occurred_at||event.created_at;
  return `<button type="button" class="audit-row" data-event-id="${esc(event.event_id||event.id)}"><time>${esc(formatBeijingTime(time))}</time><span class="audit-row-summary"><strong>${esc(eventTitle(event))}</strong><small>${esc(auditScopeLabel(event,state.accounts))} · ${esc(auditSummary(event))}</small></span><span class="event-severity" data-severity="${esc(event.severity)}">${esc(auditSeverityLabel(event.severity))}</span></button>`;
}
function bindEventRows(container, events){
  const byId=new Map(events.map(event=>[String(event.event_id||event.id),event]));
  container.querySelectorAll('[data-event-id]').forEach(button=>button.onclick=()=>showAuditDetail(byId.get(button.dataset.eventId),button));
}
function renderSystemEvents(s){
  const alerts=[...(s.alerts||[]).map(item=>typeof item==='string'?{code:item}:item),...(s.scheduler_failures||[]).map(item=>({...item,code:'SCHEDULER_OPERATION_FAILED'}))];
  const active=alerts.length?alerts.map(item=>`<div class="active-alert"><strong>${esc(statusLabel(item.code))}</strong>${detailFacts([['影响对象',item.account_id||item.channel_account_id||item.operation],['原因',eventReason(item)],['发生次数',item.failure_count],['最近发生',item.last_at&&formatBeijingTime(item.last_at)],['下次重试',item.next_retry&&formatBeijingTime(item.next_retry)],['关联意图',item.intent_id]])}${renderEventDetails(item)}</div>`).join(''):'<div class="empty">当前没有活动告警</div>';
  const events=s.events||[];
  openDetail(`${marketName(state.market)} · 运行状态与告警`,`<section><h3>活动告警</h3>${active}</section><section><h3>最近事件</h3>${events.length?events.map(eventRow).join(''):'<div class="empty">暂无系统事件</div>'}</section>`,document.querySelector('#systemStatus'));
  bindEventRows(document.querySelector('#systemEventsContent'),events);
}
function openSystemEvents(){if(state.system)renderSystemEvents(state.system);else openDetail('运行状态与告警','<div class="empty">状态暂不可用</div>',document.querySelector('#systemStatus'));}
async function refreshSystem(){
  const market=requestedMarket(), version=document.querySelector('#releaseVersion');
  const seq=(state.systemSequence||0)+1;state.systemSequence=seq;
  try{
    const s=await getJson(scoped('/api/system/status',market));
    if(seq!==state.systemSequence||market!==requestedMarket())return;
    state.system=s;
    const count=systemAlertCount(s), release=releaseVersionLabel(s);
    version.textContent=release;version.classList.toggle('warning',release==='版本未知');
    const status=document.querySelector('#systemStatus');
    status.textContent=`服务${s.watchdog_healthy?'正常':'异常'} · ${count?`${count} 条告警`:'无告警'}`;
    status.setAttribute('aria-label',`${marketName(market)} · ${status.textContent}`);
    status.classList.toggle('warning',count>0);
  }catch(error){
    if(seq!==state.systemSequence||market!==requestedMarket())return;
    state.system=null;version.textContent='版本未知';version.classList.add('warning');
    document.querySelector('#systemStatus').textContent='状态不可用';
    document.querySelector('#systemStatus').title=error.message;
  }
}
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
  if(!accountViews.has(accountId))accountViews.set(accountId,{tab:'chart',records:'intents',pages:{intents:1,orders:1,fills:1}});
  return accountViews.get(accountId);
}
export function recordPage(rows,page=1){
  const pages=Math.max(1,Math.ceil(rows.length/10));
  const current=Math.max(1,Math.min(pages,Number.isInteger(page)?page:1));
  return {rows:rows.slice((current-1)*10,current*10),page:current,pages,total:rows.length};
}
function accountRecords(kind,title,columns,rows,view){
  const page=recordPage(rows,view.pages?.[kind]);
  return `<section id="record-panel-${kind}" role="tabpanel" aria-labelledby="record-tab-${kind}" ${(view.records||'intents')===kind?'':'hidden'} class="panel section" data-account-section="${kind}" data-record-panel="${kind}"><div class="section-head"><h2>${title}</h2><span class="subtle">共 ${page.total} 条</span></div>${rowsTable(columns,page.rows)}<div class="record-pagination"><span>第 ${page.page} / ${page.pages} 页 · 每页 10 条</span><button type="button" class="button" data-page-direction="previous" data-record-page="${page.page-1}" data-record-kind="${kind}" ${page.page===1?'disabled':''}>上一页</button><button type="button" class="button" data-page-direction="next" data-record-page="${page.page+1}" data-record-kind="${kind}" ${page.page===page.pages?'disabled':''}>下一页</button></div></section>`;
}
export function accountMarkup(snapshot,accountList=state.accounts,view={}){
  const a=snapshot.account,m=snapshot.metrics||{},d=snapshot.decision||{},scope=snapshot.scope,intents=snapshot.intents||[],orders=snapshot.orders||[],fills=snapshot.fills||[];
  const executionState=decisionExecutionLabel(d),effect=d.execution_effect;
  const judgment=d.decision_id?d.strategy_output?.explanation?.judgment:null;
  const orderAction=d.decision_id?`执行计划 ${decisionPlanActionLabel(d)}`:'暂无决策';
  const decisionHeadline=judgment||orderAction;
  const orderSummary=judgment?` · ${orderAction}`:'';
  const weightSummary=effect?.availability==='AVAILABLE'?`目标 ${pct(effect.target_weight)} · 实际 ${pct(effect.actual_weight)}`:'仓位对照不可用';
  const currency=scope.currency||'CNY';
  const cash=value=>value==null?'—':`${money(value)} ${currency}`;
  const accounts=sortVirtualAccounts(accountList.filter(item=>item.run_state!=='RETIRED'));
  const gapActions=intents.filter(item=>item.attention_required).map(item=>`<div class="alert execution-gap"><strong>前瞻执行缺口</strong> · ${esc(item.attention_reason||statusLabel(item.status))}<button class="button secondary" type="button" data-ack-intent="${esc(item.intent_id)}">复核后确认</button></div>`).join('');
  const tab=view.tab||'chart',recordTab=view.records||'intents';
  return `<div class="layout account-layout" data-account-page data-account-id="${esc(scope.account_id)}">
    <aside class="sidebar" data-account-section="sidebar"><h2>虚拟账户</h2><label class="account-picker">切换账户<select id="accountPicker">${accounts.map(item=>`<option value="${esc(item.account_id)}" ${item.account_id===scope.account_id?'selected':''}>${esc(item.name||item.account_id)} · ${esc(accountOperatingStatus(item))}</option>`).join('')}</select></label><div class="account-cards">${accounts.map(item=>{
      const name=esc(item.name||item.account_id),status=esc(`${item.release_id??'—'} · ${accountOperatingStatus(item)}`),assets=`资产 ${money(item.total_assets)}`;
      return `<button class="account-card ${item.account_id===scope.account_id?'active':''}" data-account="${esc(item.account_id)}"><strong title="${name}">${name}</strong><small title="${status}">${status}</small><small title="${assets}">${assets}</small></button>`;
    }).join('')}</div></aside>
    <div class="workspace">
      <section class="panel hero account-hero" data-account-section="hero"><div class="account-heading"><div class="subtle">${marketName(scope.market)} · ${esc(scope.release_id)} · ${esc(a.symbol)} · Futu</div><h1>${esc(a.name)} <span class="badge">${esc(accountOperatingStatus(a))}</span></h1></div><div class="account-actions"><a class="button" data-account-audit href="/audit-events?${auditQuery({account_id:scope.account_id})}">审计事件</a><button type="button" id="accountDetails" class="button" aria-haspopup="dialog">账户详情</button><button id="accountSwitch" ${a.run_state==='RETIRED'?'disabled':''} class="switch ${a.run_state==='PAUSED'?'paused':''}" role="switch" aria-checked="${a.run_state==='RUNNING'}">${a.run_state==='RETIRED'?'已退出':a.run_state==='PAUSED'?'恢复账户':'暂停账户'}</button></div></section>
      <div data-account-section="alerts">${alerts(snapshot.alerts)}${gapActions}</div>
      <div class="grid account-metrics primary-metrics" data-account-section="metrics">${metric(a.run_state==='RETIRED'?'已回收资金':'总资产',cash(a.run_state==='RETIRED'?a.released_cash:a.total_assets))}${metric('可用现金',cash(a.cash))}${metric('冻结资金',cash(a.frozen_cash))}${metric('持仓',formatQuantity(a.quantity))}${metric('累计收益率',pct(m.current_total_return))}</div>
      <section class="panel account-decision" data-account-section="decision"><div class="decision-summary"><div><span class="subtle">最近决策 · 信号日 ${esc(d.signal_date||'—')} · 有效日 ${esc(d.valid_session||'—')}</span><div><strong>${esc(decisionHeadline)}</strong><span>${esc(orderSummary)} · ${esc(weightSummary)} · ${esc(executionState)}</span></div></div><button type="button" class="button secondary" id="decisionDetails" aria-haspopup="dialog">决策详情</button></div></section>
      <div class="account-tabs" role="tablist" aria-label="账户视图">${[['chart','前瞻观察'],['records','交易记录'],['performance','绩效']].map(([key,label])=>`<button type="button" role="tab" id="account-tab-${key}" aria-controls="account-panel-${key}" aria-selected="${tab===key}" tabindex="${tab===key?0:-1}" data-account-tab="${key}">${label}</button>`).join('')}</div>
      <section id="account-panel-chart" role="tabpanel" aria-labelledby="account-tab-chart" data-account-panel="chart" ${tab==='chart'?'':'hidden'} class="panel section account-chart" data-account-section="chart"><div class="section-head"><span class="subtle">选型截止 ${esc(a.selection_data_cutoff)} · 首个信号前为行情背景</span><a id="expandAccountChart" class="button" target="_blank" rel="noopener" hidden>展开大图 ↗</a></div><div id="accountChartMessage" class="chart-message" hidden></div><div id="accountChartFrameHost" class="chart-frame-host"><div class="loading">正在加载前瞻观察图…</div></div></section>
      <div id="account-panel-records" role="tabpanel" aria-labelledby="account-tab-records" data-account-panel="records" ${tab==='records'?'':'hidden'}><div class="record-tabs" role="tablist" aria-label="交易记录类型">${[['intents','订单意图'],['orders','订单'],['fills','成交']].map(([key,label])=>`<button type="button" role="tab" id="record-tab-${key}" aria-controls="record-panel-${key}" aria-selected="${recordTab===key}" tabindex="${recordTab===key?0:-1}" data-record-tab="${key}">${label}</button>`).join('')}</div>
      ${accountRecords('intents','订单意图',[['决策ID',r=>r.decision_id],['计划环节',r=>planRoleLabel(r.payload?.role)],['计划时点',r=>r.payload?.checkpoint||'—'],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['委托价',r=>orderPriceLabel(r)==='市价'?'市价':formatPrice(orderPriceLabel(r))],['有效交易日',r=>r.valid_session],['状态',r=>statusLabel(r.status)],['Futu订单',r=>r.channel_order_id||'—']],intents,view)}
      ${accountRecords('orders','订单',[['账户',r=>r.account_id],['Futu订单',r=>r.channel_order_id],['下单时间',r=>formatBeijingTime(r.created_at)],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['委托价',r=>orderPriceLabel(r)==='市价'?'市价':formatPrice(orderPriceLabel(r))],['状态',r=>statusLabel(r.status)]],orders,view)}
      ${accountRecords('fills','成交',[['账户',r=>r.account_id],['成交ID',r=>displayFillId(r.fill_id),r=>r.fill_id],['时间',r=>formatBeijingTime(r.occurred_at)],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['成交价（不复权）',r=>formatPrice(r.price)]],fills,view)}</div>
      <section id="account-panel-performance" role="tabpanel" aria-labelledby="account-tab-performance" data-account-panel="performance" ${tab==='performance'?'':'hidden'} class="panel section" data-account-section="performance">
        <div class="section-head"><h2>日终绩效</h2><span class="subtle">截至 ${esc(m.observation_end||'暂无日终快照')}</span></div>
        <div class="grid account-metrics performance-metrics">
          ${metric('日终累计收益',pct(m.total_return))}${metric('最大回撤',pct(m.maximum_drawdown))}${metric('卡玛比率',m.calmar_ratio==null?'不可用':Number(m.calmar_ratio).toFixed(3))}
          ${metric('已闭合交易',esc(m.closed_trades||0))}${metric('已闭合胜率',pct(m.win_rate))}${metric('已闭合盈亏比',closedWinLossRatio(m))}
        </div>
      </section>
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
    if(existing.hasAttribute('data-record-panel'))fresh.style.minHeight=`${existing.getBoundingClientRect().height}px`;
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
  if(!replaceAccountSections(markup,scope.account_id)){
    const sidebar=document.querySelector('.sidebar');
    const navigation=sidebar?{view:captureView(sidebar),top:sidebar.scrollTop}:null;
    document.querySelector('#app').innerHTML=markup;
    if(navigation){
      const next=document.querySelector('.sidebar');
      restoreView(next,navigation.view);next.scrollTop=navigation.top;
      document.querySelector('#accountPicker').value=scope.account_id;
    }
  }
  bindAccountEvents(scope.account_id,a.run_state);
  applyAccountView(scope.account_id);
}
async function retryAccountChart(accountId){
  if(state.navigation)return;
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
  message.title=status.message||'';
  const expand=document.querySelector('#expandAccountChart');
  const view=accountView(status.scope.account_id);
  expand.hidden=!status.chart_url;
  const chartUrl=()=>view.chartDate?`${status.chart_url}#${view.chartDate}`:status.chart_url;
  if(status.chart_url)expand.href=chartUrl();
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
    host.innerHTML=`<iframe id="accountChartFrame" data-account-id="${esc(status.scope.account_id)}" title="${esc(status.scope.release_id)}前瞻观察图" src="${esc(chartUrl())}"></iframe>`;
    const frame=document.querySelector('#accountChartFrame');
    const app=document.querySelector('#app');
    frame.onload=()=>{
      if(!frame.isConnected)return;
      const doc=frame.contentDocument;
      const chart=doc?.querySelector('#pte-forward-chart');
      if(!chart)return;
      const updateDate=()=>{
        view.chartDate=chart.dataset.selectedDate;
        if(frame.isConnected)expand.href=chartUrl();
      };
      const resize=new ResizeObserver(()=>{
        const height=Math.ceil(chart.getBoundingClientRect().height);
        // Keep the last measured height while the next account's frame loads.
        if(frame.isConnected&&height>0)app.style.setProperty('--chart-content-height',`${height}px`);
      });
      resize.observe(chart);
      frame.contentWindow.addEventListener('pagehide',()=>resize.disconnect(),{once:true});
      doc.addEventListener('pte-chart-date',updateDate);
      updateDate();
      doc?.querySelector(`[data-range="${view.chartRange||'all'}"]`)?.click();
      doc?.addEventListener('click',event=>{const range=event.target.closest('[data-range]');if(range)view.chartRange=range.dataset.range;});
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
function bindAccountEvents(accountId,runState){
  const view=accountView(accountId);
  document.querySelectorAll('[data-account]').forEach(el=>el.onclick=()=>navigate(`/accounts/${encodeURIComponent(el.dataset.account)}`));
  document.querySelector('#accountPicker').onchange=event=>navigate(`/accounts/${encodeURIComponent(event.target.value)}`);
  document.querySelector('[data-account-audit]').onclick=event=>{event.preventDefault();navigate(event.currentTarget.getAttribute('href'));};
  document.querySelector('#accountDetails').onclick=event=>{
    const {account:a,scope,metrics}=state.accountSnapshot;
    openDetail('账户详情',detailFacts([
      ['账户',a.name],['账户 ID',scope.account_id],['渠道账户',scope.channel_account_id],
      ['市场与币种',`${marketName(scope.market)} · ${scope.currency||'CNY'}`],['发布哈希',scope.release_hash],
      ['资格',qualificationLabel(a.qualification_snapshot)],['选择截止',a.selection_data_cutoff],
      ['前瞻观察起点',a.forward_observation_start||'等待首个信号'],['账务更新',formatBeijingTime(a.updated_at)],['日终估值',a.last_settlement_session],
      ['冻结资金',`${money(a.frozen_cash)} ${scope.currency||'CNY'}`],['当前累计收益',pct(metrics?.current_total_return)],
    ])+executionEffectMarkup(state.accountSnapshot.decision,scope.currency||'CNY'),event.currentTarget);
  };
  document.querySelector('#decisionDetails').onclick=event=>{
    const d=state.accountSnapshot.decision||{},currency=state.accountSnapshot.scope.currency||'CNY';
    openDetail('决策详情',decisionDetailsMarkup(d,currency),event.currentTarget);
  };
  for(const [selector,key,attribute] of [['[data-account-tab]','tab','accountTab'],['[data-record-tab]','records','recordTab']]){
    const buttons=[...document.querySelectorAll(selector)];
    buttons.forEach((el,index)=>{
      el.onclick=()=>updateView(document.querySelector('#app'),()=>{view[key]=el.dataset[attribute];applyAccountView(accountId);});
      el.onkeydown=event=>{
        const next={ArrowRight:(index+1)%buttons.length,ArrowLeft:(index+buttons.length-1)%buttons.length,Home:0,End:buttons.length-1}[event.key];
        if(next==null)return;event.preventDefault();buttons[next].click();buttons[next].focus({preventScroll:true});
      };
    });
  }
  document.querySelectorAll('[data-record-page]').forEach(el=>el.onclick=()=>updateView(document.querySelector('#app'),()=>{view.pages[el.dataset.recordKind]=Number(el.dataset.recordPage);renderAccount(state.accountSnapshot);}));
  document.querySelector('#accountSwitch').onclick=async()=>{
    if(state.navigation)return;
    const resume=runState==='PAUSED', action=resume?'恢复':'暂停';
    if(!confirm(`确认${action}${marketName(state.market)}账户 ${accountId}？`))return;
    try{await post(`/api/virtual-accounts/${encodeURIComponent(accountId)}/${resume?'resume':'pause'}`);toast(`账户已${action}`);await loadRoute({showLoading:false});}
    catch(error){toast(error.message);}
  };
  document.querySelectorAll('[data-ack-intent]').forEach(el=>el.onclick=async()=>{if(state.navigation)return;const note=prompt('请填写执行缺口复核结论：');if(!note?.trim())return;try{await post(`/api/virtual-accounts/${encodeURIComponent(accountId)}/intents/${encodeURIComponent(el.dataset.ackIntent)}/acknowledge`,{resolution_note:note.trim()});toast('执行缺口已确认');await loadRoute({showLoading:false});}catch(e){toast(e.message);}});
}

export function channelMarkup(s){
  const id=s.scope?.channel_account_id||'futu-cn-default',currency=s.currency||'CNY';
  const cash=value=>value==null?'—':`${money(value)} ${currency}`;
  const cashAvailable=s.cash_difference!=null, cashOk=cashAvailable&&Math.abs(Number(s.cash_difference))<=.01;
  const cashState=cashAvailable?(cashOk?'资金对账正常':'资金对账异常'):'资金数据不可用';
  const assetState=s.asset_difference==null?'估值数据不可用':Math.abs(Number(s.asset_difference))<=.01?'估值一致':'估值口径不同';
  const accounts=s.strategy_accounts||s.accounts||[];
  const orders=s.orders||[];
  const rows=orders.map((order,index)=>`<tr><td>${esc(formatBeijingTime(order.created_at))}</td><td>${esc(order.channel_order_id)}</td><td>${esc(channelOrderAccountLabel(order))}</td><td>${esc(order.decision_id)}</td><td>${esc(sideLabel(order.side))}</td><td>${formatQuantity(order.quantity)}</td><td>${esc(orderPriceLabel(order)==='市价'?'市价':formatPrice(orderPriceLabel(order)))}</td><td>${esc(statusLabel(order.status))}</td><td>${['SUBMITTED','FILLED_PART'].includes(order.status)&&order.account_id?`<button type="button" class="button secondary" data-cancel-order="${index}">申请撤单</button>`:'—'}</td></tr>`).join('');
  return `<section class="workspace" data-channel-section="${esc(id)}">
    <section class="panel hero"><div><div class="eyebrow">Futu 模拟渠道 · ${esc(id)} · ${currency}</div><h1>${marketName(s.market)}模拟盘</h1><div class="subtle">${s.paused?'已暂停':'运行中'} · 对账 ${esc(statusLabel(s.reconciliation_status))} · 最近对账 ${esc(formatBeijingTime(s.last_reconcile_at))}</div></div><div class="account-actions"><button class="button secondary" data-reconciliation type="button" aria-haspopup="dialog">对账详情</button><button type="button" class="switch ${s.paused?'paused':''}" data-channel-switch role="switch" aria-checked="${!s.paused}">${s.paused?'恢复渠道':'暂停渠道'}</button></div></section>
    ${alerts((s.alerts||[]).map(code=>({message:statusLabel(code)})))}
    <div class="grid channel-core-metrics">${metric('券商总资产',cash(s.account?.total_assets))}${metric('券商现金',cash(s.broker_cash??s.account?.cash))}${metric('PTE 账务现金',cash(s.logical_cash))}${metric('现金差额',cash(s.cash_difference))}</div>
    <div class="panel reconciliation-summary"><strong>${cashState}</strong><span class="subtle"> · ${assetState}</span></div>
    <section class="panel section"><div class="section-head"><h2>策略账户</h2><span class="subtle">${accounts.length} 个账户</span></div>${rowsTable([['虚拟账户',r=>r.name],['账户 ID',r=>r.account_id],['策略版本',r=>r.release_id],['标的',r=>r.symbol],['分配额度',r=>cash(r.initial_cash)],['可用现金',r=>cash(r.cash)],['冻结资金',r=>cash(r.frozen_cash)],['持仓',r=>formatQuantity(r.quantity)],['状态',accountOperatingStatus]],accounts)}</section>
    <section class="panel section"><div class="section-head"><h2>渠道持仓</h2></div>${rowsTable([['标的',r=>r.symbol],['持仓',r=>formatQuantity(r.quantity)],['可卖',r=>formatQuantity(r.sellable_quantity)]],s.positions)}</section>
    <section class="panel section"><div class="section-head"><h2>订单</h2></div>${rows?'<div class="table-wrap"><table><thead><tr><th>时间</th><th>订单 ID</th><th>账户</th><th>决策 ID</th><th>方向</th><th>数量</th><th>委托价</th><th>状态</th><th>操作</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'<div class="empty">暂无记录</div>'}</section>
    <section class="panel section"><div class="section-head"><h2>成交</h2></div>${rowsTable([['时间',r=>formatBeijingTime(r.occurred_at)],['账户',channelOrderAccountLabel],['成交 ID',r=>displayFillId(r.fill_id),r=>r.fill_id],['订单 ID',r=>r.order_id],['方向',r=>sideLabel(r.side)],['数量',r=>formatQuantity(r.quantity)],['价格',r=>formatPrice(r.price)],['费用',r=>cash(r.fee)]],s.fills)}</section>
  </section>`;
}
function renderChannel(s){
  const snapshots=Array.isArray(s)?s:[s];
  const app=document.querySelector('#app');
  app.innerHTML=snapshots.length?snapshots.map(channelMarkup).join(''):`<section class="panel hero"><h1>${marketName(state.market)}模拟盘</h1><p>当前市场没有已配置的模拟渠道。</p></section>`;
  app.querySelectorAll('[data-channel-section]').forEach((section,index)=>{
    const snapshot=snapshots[index],id=section.dataset.channelSection,currency=snapshot.currency||'CNY';
    const prefix='/api/channel-accounts/'+encodeURIComponent(id);
    section.querySelector('[data-channel-switch]').onclick=async()=>{
      if(state.navigation)return;
      const action=snapshot.paused?'恢复':'暂停';
      if(!confirm(`确认${action}${marketName(snapshot.market)}模拟渠道 ${id}？`))return;
      try{await post(prefix+(snapshot.paused?'/resume':'/pause'));toast(`渠道已${action}`);await loadRoute({showLoading:false});}
      catch(error){toast(error.message);}
    };
    section.querySelector('[data-reconciliation]').onclick=event=>openDetail('对账详情',detailFacts([
      ['渠道账户',id],['币种',currency],['最近对账',formatBeijingTime(snapshot.last_reconcile_at)],
      ['券商总资产',money(snapshot.account?.total_assets)],['券商持仓市值',money(snapshot.account?.market_value)],
      ['PTE 日终总资产',money(snapshot.logical_total_assets)],['估值差额',money(snapshot.asset_difference)],
      ['已分配额度',money(snapshot.strategy_allocated_capital)],['未分配额度',money(snapshot.unallocated_capital)],
      ['平账账户余额',money(snapshot.reconciliation_account?.cash)],
    ])+'<p class="subtle">券商按当前行情估值，PTE 账务总资产按最近日终数据估值。</p>',event.currentTarget);
    section.querySelectorAll('[data-cancel-order]').forEach(button=>button.onclick=()=>{
      if(!state.navigation)cancelOrder(snapshot.orders[Number(button.dataset.cancelOrder)],prefix,marketName(snapshot.market),id);
    });
  });
}
async function cancelOrder(order,prefix,market,channel){
  const scope=`${market} · ${channel} · ${channelOrderAccountLabel(order)} · ${order.channel_order_id}`;
  if(!confirm(`申请撤销订单？\n${scope}\n${sideLabel(order.side)} ${formatQuantity(order.quantity)}`))return;
  try{
    const body={account_id:order.account_id,channel_order_id:order.channel_order_id};
    const {token}=await post(prefix+'/cancel-token',body);
    if(!confirm(`撤单令牌已签发，有效期 2 分钟。再次确认撤单？\n${scope}`))return;
    await post(prefix+'/cancel',{...body,token});
    toast('撤单请求已提交');await loadRoute({showLoading:false});
  }catch(error){toast(error.message);}
}

function renderComparison(snapshot){
  const columns = [
    ['账户', row=>row.account_id],
    ['策略发布', row=>row.release_id],
    ['绩效估值窗口', ({metrics})=>metrics.observation_start&&metrics.observation_end
      ? `${metrics.observation_start} 至 ${metrics.observation_end}` : '尚无日终快照'],
    ['交易日', ({metrics})=>metrics.observation_count??0],
    ['累计收益', ({metrics})=>pct(metrics.total_return)],
    ['最大回撤', ({metrics})=>pct(metrics.maximum_drawdown)],
    ['卡玛比率', ({metrics})=>metrics.calmar_ratio==null?'不可用':Number(metrics.calmar_ratio).toFixed(3)],
    ['已闭合交易', ({metrics})=>metrics.closed_trades??0],
    ['已闭合胜率', ({metrics})=>pct(metrics.win_rate)],
    ['已闭合盈亏比', ({metrics})=>closedWinLossRatio(metrics)],
  ];
  document.querySelector('#app').innerHTML=`
    <section class="panel hero"><div><div class="eyebrow">只读评估</div><h1>虚拟账户比较</h1><div class="subtle">各账户按自身日终估值窗口统计，指标与账户详情页保持一致</div></div></section>
    <section class="panel section">
      <div class="section-head"><h2>参与账户</h2><span class="badge">无交易干预</span></div>
      <div class="comparison-select">${state.accounts.map(account=>`<label><input type="checkbox" value="${esc(account.account_id)}" ${snapshot.accounts.some(row=>row.account_id===account.account_id)?'checked':''}> ${esc(account.name)} · ${esc(account.release_id)}</label>`).join('')}</div>
    </section>
    <section class="panel section">
      <div class="section-head"><h2>核心指标</h2><span class="badge">OPC优先级</span></div>
      ${rowsTable(columns,snapshot.accounts)}
    </section>`;
  document.querySelectorAll('.comparison-select input').forEach(input=>input.onchange=()=>{
    const ids=[...document.querySelectorAll('.comparison-select input:checked')].map(item=>item.value);
    navigate('/comparison?'+comparisonQuery(ids));
  });
}

function renderAudit(s){
  const selected=new URLSearchParams(location.search),categories=['STRATEGY','TRADING','SYSTEM','OTHER'];
  const options=categories.map(category=>`<option value="${category}" ${selected.get('category')===category?'selected':''}>${auditCategoryLabel(category)} · ${s.category_counts?.[category]||0}</option>`).join('');
  const events=s.events||[], app=document.querySelector('#app');
  app.innerHTML=`<section class="panel hero"><div><div class="eyebrow">${marketName(state.market)} · 北京时间</div><h1>审计事件</h1><div class="subtle">最近同步 ${esc(formatBeijingTime(s.as_of))}</div></div></section>
    <section class="panel section"><form id="auditFilters" class="audit-filters"><label>类别<select name="category"><option value="">全部类别</option>${options}</select></label><label>账户<input name="account_id" value="${esc(selected.get('account_id')||'')}" placeholder="账户 ID"></label><label>策略<input name="strategy_id" value="${esc(selected.get('strategy_id')||'')}" placeholder="策略 ID"></label><label>渠道<input name="channel" value="${esc(selected.get('channel')||'')}" placeholder="渠道类型"></label><label>关联 ID<input name="correlation_id" value="${esc(selected.get('correlation_id')||'')}" placeholder="决策或发布链路"></label><button class="button" type="submit">筛选</button><button class="button secondary" id="clearAuditFilters" type="button">清空</button></form></section>
    <section class="panel section"><div class="section-head"><h2>运行记录</h2><span class="subtle">${events.length} 条</span></div><div class="audit-list">${events.length?events.map(eventRow).join(''):'<div class="empty">当前筛选条件下暂无事件</div>'}</div>${s.next_before_id?'<button id="moreAudit" class="button secondary" type="button">下一页 · 更早事件</button>':''}</section>`;
  bindEventRows(app,events);
  document.querySelector('#auditFilters').onsubmit=event=>{event.preventDefault();const query=auditQuery(Object.fromEntries(new FormData(event.currentTarget)));navigate(`/audit-events${query?'?'+query:''}`);};
  document.querySelector('#clearAuditFilters').onclick=()=>navigate('/audit-events');
  const more=document.querySelector('#moreAudit');
  if(more)more.onclick=()=>{const params=new URLSearchParams(location.search);params.set('before_id',s.next_before_id);navigate(`/audit-events?${params}`,false,Math.max(0,document.querySelector('.audit-list').getBoundingClientRect().top+window.scrollY-130));};
}

async function loadAccounts(market,options={}){return getJson(scoped('/api/virtual-accounts',market),options);}
async function loadRoute({showLoading=true,forceRender=false}={}){
  const route=parseRoute(location.pathname);setNav(route.page);
  const market=requestedMarket();
  state.market=market;
  document.querySelectorAll('[data-market]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.market===market)));
  const scope=`${market}:${route.page==='account'?route.accountId:`${route.page}${location.search}`}`;
  const request=state.loader.begin(scope);
  try{
    if(showLoading)document.querySelector('#app').innerHTML='<div class="loading">正在加载当前作用域…</div>';
    const accountIndex=await loadAccounts(market,{signal:request.signal});
    if(!state.loader.accept(request,scope))return;
    state.accounts=accountIndex.accounts||[];
    if(route.page==='account'){
      const storageKey=`pte.lastAccountId.${market}`;
      const requested=route.accountId||localStorage.getItem(storageKey);
      if(route.accountId&&!state.accounts.some(row=>row.account_id===route.accountId)&&!new URLSearchParams(location.search).has('market')){
        const all=await getJson('/api/virtual-accounts',{signal:request.signal});
        if(!state.loader.accept(request,scope))return;
        const account=all.accounts?.find(row=>row.account_id===route.accountId);
        if(validMarket(account?.market)&&account.market!==market){navigate(scoped(location.pathname,account.market),true,0);return;}
      }
      const id=route.accountId&&state.accounts.some(row=>row.account_id===route.accountId)?route.accountId:
        route.accountId?null:chooseAccountId(requested,state.accounts,accountIndex.default_account_id);
      if(!id){
        document.querySelector('#app').innerHTML=`<section class="panel hero"><div><h1>虚拟账户</h1><p>${route.accountId?'当前市场没有此账户。':'暂无可展示的虚拟账户。'}</p></div></section>`;
        document.querySelector('#pollWarning').hidden=true;
        localStorage.removeItem(storageKey);
        state.renderedScope=null;state.fingerprint=null;state.chart=null;
        finishNavigation();
        return;
      }
      if(route.accountId!==id){navigate(`/accounts/${encodeURIComponent(id)}`,true);return;}
    }
    let snapshot,chartPromise=null;
    if(route.page==='account'){
      chartPromise=getJson(`/api/virtual-accounts/${encodeURIComponent(route.accountId)}/chart`,{signal:request.signal}).catch(error=>({scope:{account_id:route.accountId},status:'UNAVAILABLE',chart_url:null,fingerprint:null,message:error.message}));
      snapshot=await getJson(`/api/virtual-accounts/${encodeURIComponent(route.accountId)}/snapshot`,{signal:request.signal});
    }
    else if(route.page==='channel'){
      const index=await getJson(scoped('/api/channel-accounts',market),{signal:request.signal});
      snapshot=await Promise.all(index.channels.map(async channel=>{
        const value=await getJson(`/api/channel-accounts/${encodeURIComponent(channel.channel_account_id)}/snapshot`,{signal:request.signal});
        if(value.market!==market||value.scope.channel_account_id!==channel.channel_account_id)throw new Error('服务端渠道作用域不一致');
        return value;
      }));
    }
    else if(route.page==='comparison'){
      const selection=new URLSearchParams(location.search);
      const query=selection.has('account_id')?'?'+comparisonQuery(selection.getAll('account_id').filter(Boolean)):'';
      snapshot=await getJson(scoped('/api/comparison'+query,market),{signal:request.signal});
    }
    else snapshot=await getJson(scoped(`/api/audit-events${location.search}`,market),{signal:request.signal});
    if(!state.loader.accept(request,scope))return;
    if(!state.navigation&&document.querySelector('#systemEventsDialog')?.open)return;
    if(route.page==='account'&&(snapshot.scope.account_id!==route.accountId||snapshot.scope.market!==market))throw new Error('服务端账户作用域不一致');
    const fingerprint=snapshotFingerprint({accounts:state.accounts,snapshot});
    if(forceRender||scope!==state.renderedScope||fingerprint!==state.fingerprint){
      const sameScope=scope===state.renderedScope;
      updateView(document.querySelector('#app'),()=>{
      if(route.page==='account'){localStorage.setItem(`pte.lastAccountId.${market}`,route.accountId);renderAccount(snapshot);}
      else if(route.page==='channel')renderChannel(snapshot);else if(route.page==='comparison')renderComparison(snapshot);else renderAudit(snapshot);
      },{preserve:sameScope,y:state.navigation?.y??window.scrollY});
      state.renderedScope=scope;state.fingerprint=fingerprint;
    }
    if(state.navigation)updateView(document.querySelector('#app'),()=>{},{preserve:false,y:state.navigation.y});
    finishNavigation();
    if(route.page==='account'){
      const chartStatus=await chartPromise;
      if(!state.loader.accept(request,scope)||chartStatus.scope.account_id!==route.accountId)return;
      applyAccountChart(chartStatus);
    }
    state.lastSuccess=new Date();
    const warning=document.querySelector('#pollWarning');warning.hidden=true;warning.textContent='';
  }catch(error){
    if(error.name==='AbortError'||!state.loader.accept(request,scope))return;
    const message=`刷新失败：${error.message} · 继续显示最后成功数据`;
    const warning=document.querySelector('#pollWarning');warning.hidden=false;warning.textContent=message;
    if(showLoading||state.renderedScope!==scope){
      updateView(document.querySelector('#app'),()=>{document.querySelector('#app').innerHTML=`<div class="error route-error"><strong>当前作用域加载失败</strong><div>${esc(error.message)}</div><button id="retryRoute" class="button">重新加载当前页面</button></div>`;},{preserve:false,y:state.navigation?.y??window.scrollY});
      document.querySelector('#retryRoute').onclick=()=>navigate(`${location.pathname}${location.search}`,true);
      state.renderedScope=null;state.fingerprint=null;
      warning.textContent=`加载失败：${error.message}`;
    }
    finishNavigation();
  }
}
function finishNavigation(){
  state.navigation=null;
  document.querySelector('#routeLoading').hidden=true;
  document.querySelector('#app').removeAttribute('aria-busy');
  document.querySelectorAll('[data-navigation-disabled]').forEach(el=>{el.disabled=false;delete el.dataset.navigationDisabled;});
}
function beginNavigation(y,followScroll=false){
  state.navigation={y,followScroll};
  reserveViewport(document.querySelector('#app'),y);
  const notice=document.querySelector('#routeLoading');
  const route=parseRoute(location.pathname);
  const account=state.accounts.find(item=>item.account_id===route.accountId);
  notice.textContent=`正在加载 ${route.page==='account'?(account?.name||route.accountId||'虚拟账户'):'页面'}…`;
  notice.hidden=false;
  document.querySelector('#app').setAttribute('aria-busy','true');
  document.querySelectorAll('#accountSwitch,[data-ack-intent],#retryAccountChart,[data-channel-switch],[data-cancel-order]').forEach(el=>{if(!el.disabled){el.dataset.navigationDisabled='';el.disabled=true;}});
}
function navigate(url,replace=false,targetY=null){
  const market=new URLSearchParams(url.split('?')[1]).get('market');
  if(!validMarket(market))url=scoped(url,requestedMarket());
  const current=`${location.pathname}${location.search}`;
  const samePage=parseRoute(url.split('?')[0]).page===parseRoute(location.pathname).page;
  const y=targetY??(samePage?window.scrollY:0);
  history.replaceState({...history.state,pteScroll:window.scrollY},'',current);
  if(url!==current)history[replace?'replaceState':'pushState']({pteScroll:y},'',url);
  const changed=syncMarket();
  beginNavigation(y,samePage&&targetY==null);
  loadRoute(changed?{showLoading:true}:navigationOptions(state.renderedScope));
}
function syncMarket(){
  const market=requestedMarket();
  localStorage.setItem('pte.market',market);
  if(market===state.market)return false;
  state.market=market;state.system=null;
  const status=document.querySelector('#systemStatus');
  status.textContent='状态加载中';status.classList.remove('warning');
  refreshSystem();
  return true;
}
function switchMarket(market){
  if(market===requestedMarket())return;
  const route=parseRoute(location.pathname),params=new URLSearchParams(location.search);
  for(const key of ['account_id','strategy_id','channel','channel_account_id','correlation_id','decision_id','order_id','before_id'])params.delete(key);
  params.set('market',market);
  const path=route.page==='account'?'/accounts/':route.page==='channel'?'/channels':location.pathname;
  navigate(`${path}?${params}`,false,0);
}
function boot(){
  history.scrollRestoration='manual';
  document.querySelector('#reloadConsole').onclick=()=>location.reload();
  document.querySelectorAll('a[href^="/"]').forEach(a=>a.onclick=e=>{e.preventDefault();navigate(a.getAttribute('href'));});
  document.querySelector('#systemStatus').onclick=openSystemEvents;
  const dialog=document.querySelector('#systemEventsDialog');
  document.querySelector('#closeSystemEvents').onclick=()=>dialog.close();
  dialog?.addEventListener('close',()=>{
    window.scrollTo({top:state.detailScroll,left:window.scrollX,behavior:'instant'});
    if(state.detailTrigger?.isConnected)state.detailTrigger.focus({preventScroll:true});
    state.detailTrigger=null;
  });
  document.querySelectorAll('[data-market]').forEach(button=>button.onclick=()=>switchMarket(button.dataset.market));
  window.addEventListener('popstate',event=>{const changed=syncMarket();beginNavigation(event.state?.pteScroll??0);loadRoute(changed?{showLoading:true}:navigationOptions(state.renderedScope));});
  window.addEventListener('scroll',()=>{
    if(state.navigation?.followScroll)state.navigation.y=window.scrollY;
    if(!state.navigation)history.replaceState({...history.state,pteScroll:window.scrollY},'');
  },{passive:true});
  state.market=requestedMarket();refreshSystem();loadRoute({showLoading:true,forceRender:true});
  setInterval(refreshSystem,10000);
  setInterval(()=>{if(!state.navigation&&!dialog?.open)loadRoute({showLoading:false});},5000);
}
if(typeof document!=='undefined')boot();
