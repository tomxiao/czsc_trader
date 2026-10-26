window.mountStrategyChart=function mountStrategyChart(root,context){
  if(!(root instanceof HTMLElement)||!context||!['BACKTEST','PAPER'].includes(context.mode)||!context.strategy||!context.window||!context.market_data||!context.execution||![context.market_data.bars,context.observations,context.execution.decisions,context.execution.fills,context.execution.snapshots].every(Array.isArray))throw new TypeError('strategy chart requires a container and typed chart context');
  if(root.dataset.strategyChartMounted)throw new Error('strategy chart is already mounted');
  root.dataset.strategyChartMounted='true';root.classList.add('strategy-chart');
  const lifecycle=new AbortController();let destroyed=false;
  const listen=(node,type,handler)=>node.addEventListener(type,handler,{signal:lifecycle.signal});
  const stage=root.querySelector('#forward-stage');
  const svg=root.querySelector('#forward-svg');
  const tooltip=root.querySelector('#forward-tooltip');
  if(!stage||!svg||!tooltip){delete root.dataset.strategyChartMounted;throw new TypeError('strategy chart requires the shared chart shell');}
  const embedded=window.parent!==window;
  if(embedded)root.classList.add('embedded');
  const NS='http://www.w3.org/2000/svg';
  const colors=new Map();
  const css=name=>{if(!colors.has(name))colors.set(name,getComputedStyle(root).getPropertyValue(name).trim());return colors.get(name);};
  const state={range:'all',layers:{signal:true,fill:true,position:true},selected:null,signalView:null};
  const bars=context.market_data.bars;
  const observations=context.observations;
  const decisions=[...context.execution.decisions].sort((a,b)=>Date.parse(a.generated_at)-Date.parse(b.generated_at));
  const fills=[...context.execution.fills].sort((a,b)=>Date.parse(a.occurred_at)-Date.parse(b.occurred_at));
  const snapshots=context.execution.snapshots;
  const cutoff=context.window.selection_data_cutoff;
  const byDate=new Map([...observations].sort((a,b)=>String(a.generated_at||a.signal_date).localeCompare(String(b.generated_at||b.signal_date))).map(item=>[item.signal_date,item]));
  const observationById=new Map(observations.filter(item=>item.observation.status==='READY').map(item=>[item.decision_id,item.observation]));
  const snapshotByDate=new Map(snapshots.map(item=>[item.session,item]));
  const signalControls=document.createElement('div');signalControls.className='signal-panel-controls';signalControls.hidden=true;
  const signalSelect=document.createElement('select');signalSelect.setAttribute('aria-label','选择信号分组');
  const signalUnit=document.createElement('span');signalUnit.className='signal-panel-unit';
  const signalLegend=document.createElement('div');signalLegend.className='signal-panel-legend';signalLegend.hidden=true;
  signalControls.appendChild(signalSelect);signalControls.appendChild(signalUnit);stage.appendChild(signalControls);stage.appendChild(signalLegend);
  const fmt=value=>Number(value).toLocaleString('zh-CN',{minimumFractionDigits:3,maximumFractionDigits:4});
  const shortDate=value=>String(value).slice(5);
  const actionLabel=value=>({BUY:'入场',ENTER:'入场',SELL:'退出',EXIT:'退出',ROTATE:'日内轮换',HOLD:'持有',WAIT:'等待',HOLD_POSITION:'持有',HOLD_CASH:'空仓观察',NO_EVENT:'无新增事件',INTRADAY_LONG_OVERLAY:'日内增强'}[String(value).toUpperCase()]||String(value||'无新增事件'));
  const el=(name,attrs={},text='')=>{const node=document.createElementNS(NS,name);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value)));if(text)node.textContent=text;return node;};
  const linePath=points=>points.map((point,index)=>`${index?'L':'M'}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(' ');
  const extent=values=>[Math.min(...values),Math.max(...values)];
  const scale=(domainMin,domainMax,rangeMin,rangeMax)=>value=>rangeMin+(Number(value)-domainMin)/(domainMax-domainMin||1)*(rangeMax-rangeMin);
  const safe=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const localTime=value=>{
    if(!value)return '时间未记录';
    const time=new Date(value);if(Number.isNaN(time.getTime()))return '时间格式异常';
    return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(time);
  };
  const fillDate=item=>item.session||localTime(item.occurred_at).slice(0,10);
  const fillTime=item=>item.time_precision==='SESSION'||/^\d{4}-\d{2}-\d{2}$/.test(item.occurred_at||'')?`${fillDate(item)}（交易日，未记录时刻）`:localTime(item.occurred_at);
  const statusLabel=value=>({PENDING:'待执行',EXECUTING:'执行中',COMPLETED:'已完成',SUPERSEDED:'已替代',CANCELLED:'已取消',INCOMPLETE:'未完成'}[value]||value);
  const quantity=value=>value==null?'未记录':`${Number(value).toLocaleString('zh-CN')} 股`;
  const money=value=>value==null?'未记录':`${Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})} 元`;
  const dayDecisions=date=>decisions.filter(item=>localTime(item.generated_at).slice(0,10)===date);
  const dayFills=date=>fills.filter(item=>fillDate(item)===date);
  const fillSummary=item=>`${fillTime(item)} · 成交：${String(item.side).toUpperCase()==='BUY'?'买入':'卖出'} ${quantity(item.quantity)}，价格 ${fmt(item.price)} 元（不复权），金额 ${money(Number(item.quantity)*Number(item.price))}，费用 ${money(item.fee)}`;
  const eventDates=[...new Set([...bars.map(item=>item.date),...decisions.map(item=>localTime(item.generated_at).slice(0,10)),...fills.map(fillDate)])].sort();
  const tradingDates=new Set(bars.map(item=>item.date));

  const write=(selector,text)=>{const node=root.querySelector(selector);if(node)node.textContent=text;};
  const isBacktest=context.mode==='BACKTEST';
  write('#forward-title',`${context.strategy.release_id||context.strategy.reference_id} · ${context.strategy.name||context.strategy.symbol}`);
  const observationStart=context.window.observation_start;
  write('#forward-subtitle',isBacktest?`回测复盘 · ${context.strategy.symbol} · ${context.window.start} — ${context.window.end}`:`前瞻观察 · ${context.strategy.symbol} · ${context.strategy.account_id} · ${observationStart?`观察事实自 ${observationStart}`:'等待首条观察事实'}`);
  write('#forward-asof',`${isBacktest?'回测完成':'运行正常'} · 数据截至 ${context.market_data.as_of}`);


  const reading=document.createElement('section');reading.className='signal-reading';reading.setAttribute('aria-label','策略信号解释');stage.appendChild(reading);
  const legacyNotice=document.createElement('div');legacyNotice.className='signal-legacy-notice';legacyNotice.textContent='该记录未提供解释；保留原始信号值';stage.appendChild(legacyNotice);
  let expanded=false,readingDate=null;
  const node=(tag,cls,text)=>{const element=document.createElement(tag);element.className=cls;if(text!=null)element.textContent=text;return element;};
  function paintReading(observation,date){
    if(readingDate!==date)expanded=false;readingDate=date;
    const narrative=observation?.status==='READY'?observation.signal_panel?.explanation:null;
    const legacy=observation?.status==='READY'&&!narrative;
    reading.hidden=legacy||!state.layers.signal;legacyNotice.hidden=!legacy||!state.layers.signal;
    signalControls.hidden=!legacy||!state.layers.signal||!signalSelect.options.length;
    signalLegend.hidden=signalControls.hidden;
    if(reading.hidden)return;
    const unavailable=observation?.status==='UNAVAILABLE';
    const judgment=narrative?.judgment||(unavailable?'观察不可用':'当日没有信号观察');
    const reason=unavailable?observation.message:'该日期没有记录策略观察，不据此推断入场或退出。';
    const head=node('div','reading-head');head.append(node('div','reading-label','当前判断'),node('strong','',judgment),node('span','reading-date',date));
    if(narrative){const toggle=node('button','',expanded?'返回':'解释');toggle.type='button';toggle.setAttribute('aria-label',expanded?'返回信号结论':'解释策略判断');toggle.addEventListener('click',()=>{expanded=!expanded;paintReading(observation,date);});head.append(toggle);}
    const basis=node('div','reading-basis');basis.append(node('div','reading-label',expanded?'怎么看这个判断':'判断依据'));
    const body=node('div','reading-body');
    if(expanded)body.append(node('div','reading-detail',narrative.explanation));
    else if(narrative)narrative.basis.forEach(item=>{const row=node('div','reading-row',item.text);row.dataset.basisKey=item.key;body.append(row);});
    else body.append(node('div','reading-detail',reason));
    basis.append(body);
    const next=node('div','reading-next');next.append(node('div','reading-label','接下来关注'),node('div','reading-body',narrative?.next_watch||(unavailable?'等待完整观察；交易结果以事件和账户记录为准。':'请选择有观察记录的日期。')));
    reading.replaceChildren(node('span','reading-region-label','信号'),head,basis,next);
  }

  function visibleBars(){if(state.range==='all')return bars;return bars.slice(Math.max(0,bars.length-Number(state.range)));}
  function add(node){svg.appendChild(node);return node;}
  function factValue(item){
    if(item.format==='PERCENT')return `${(Number(item.value)*100).toFixed(2)}%`;
    if(item.format==='NUMBER')return Number(item.value).toFixed(4);
    if(item.format==='BOOLEAN')return item.value?'是':'否';
    return String(item.value);
  }
  function explanation(observation){
    if(observation?.status!=='READY')return observation?.message||'当日没有策略观察事实';
    if(observation.signal_panel?.explanation){const value=observation.signal_panel.explanation;return [value.judgment,...value.basis.map(item=>item.text)].join('；');}
    return [...(observation.series||[]).map(item=>`${item.label} ${Number(item.value).toFixed(4)}${(item.guides||[]).map(guide=>` / ${guide.label} ${Number(guide.value).toFixed(4)}`).join('')}`),
      ...(observation.facts||[]).map(item=>`${item.label} ${factValue(item)}`)].join('；');
  }
  function eventLines(date){
    const events=[
      ...dayDecisions(date).map(item=>({time:item.generated_at,decision:item})),
      ...dayFills(date).map(item=>({time:item.occurred_at,fill:item})),
    ].sort((a,b)=>Date.parse(a.time)-Date.parse(b.time));
    const lines=events.flatMap(event=>{
      if(event.fill)return [fillSummary(event.fill)];
      const item=event.decision;
      const details=[`${localTime(item.generated_at)} · 决策：${actionLabel(item.action)}；目标 ${quantity(item.target_quantity)}；${statusLabel(item.status)}；生效 ${item.valid_session}；信号 ${item.signal_date}`];
      if(item.state_reason)details.push(`状态原因：${reasonLabel(item.state_reason)}；记录 ${localTime(item.state_changed_at)}`);
      const observation=observationById.get(item.decision_id);
      details.push(observation?`决策依据：${explanation(observation)}`:'决策依据：无可用于本图的策略观察事实');
      return details;
    });
    if(!lines.length)lines.push('当日无可展示的决策或成交事件');
    return lines.join('\n');
  }
  function reasonLabel(value){
    return ({
      NO_ORDER:'计划无需下单',PLAN_GENERATED:'生成待执行计划',PLAN_REPLACED:'由新决策替代',
      ACCOUNT_RETIRED:'账户退出前撤回未执行计划',SUBMISSION_STARTED:'开始提交订单',
      PLAN_FILLED:'计划全部成交',PLAN_ENDED_WITHOUT_COMPLETION:'计划全部结束，未完成原定交易',
      NORMAL_UNFILLED:'限价买单正常结束，零成交',DEPENDENCY_NOT_TRIGGERED:'前序买入未成交，条件未触发',
      CHANNEL_RESULT_UNCERTAIN:'渠道结果待确认',CHANNEL_EXECUTION:'渠道执行中',AWAITING_EXECUTION:'等待执行',
      AWAITING_FILL_RECONCILIATION:'等待成交事实对账',EXECUTION_WINDOW_PASSED:'执行时窗已结束',
      REPLACED:'由新决策替代',EXPIRED:'超过执行时限',CANCELLED:'执行前撤回',REJECTED:'订单拒绝',
      MIGRATION_NO_ORDER:'历史计划无需下单',MIGRATION_SUBMISSION_UNCERTAIN:'历史渠道提交结果待确认',
      MIGRATION_ALL_PLANNED_ORDERS_FILLED:'历史计划全部成交',
      MIGRATION_ORIGINAL_PLAN_REJECTED_OPERATOR_COMPENSATION:'原计划被拒绝，后续人工补偿成交独立保留',
      MIGRATION_UNSUBMITTED_REPLACEMENT:'历史未提交计划已被替代',MIGRATION_ALL_INTENTS_ENDED:'历史订单意图全部结束，计划未完成',
      MIGRATION_SUBMITTED_WORK_REMAINS:'历史已提交交易仍待结束',MIGRATION_VALID_SESSION_PASSED:'历史计划超过有效交易日',
      MIGRATION_UNSUBMITTED_PLAN:'历史计划尚未提交',
    }[value]||value);
  }
  function wrapExplanation(text,width,measure){
    const lines=[];
    for(const paragraph of text.split('\n')){
      let line='';
      for(const character of paragraph){
        const next=line+character;
        if(line&&measure.measureText(next).width>width){lines.push(line);line=character;}else{line=next;}
      }
      lines.push(line);
    }
    return lines;
  }
  const availabilityLabel=item=>item.status==='INACTIVE'?'当前不适用':item.status==='UNAVAILABLE'?'数据不可用':'有效';
  const signalValue=(value,group)=>`${Number(group.format==='PERCENT'?value*100:value).toLocaleString('zh-CN',{minimumFractionDigits:group.precision,maximumFractionDigits:group.precision})}${group.format==='PERCENT'?'%':''}`;
  const stateColor=index=>['--signal','--position','--fill','--up','--down'][index%5];
  function signalViews(rows){
    const views=new Map();let legacy=false;
    rows.forEach(row=>{
      const observation=byDate.get(row.date)?.observation;
      if(observation?.status!=='READY')return;
      if(!observation.signal_panel){legacy=true;return;}
      const identity=observation.definition_sha256;
      for(const [kind,items] of [['group',observation.signal_panel.groups],['state',observation.signal_panel.states]]){
        for(const item of items){const key=`${identity}:${kind}:${item.key}`;if(!views.has(key))views.set(key,{key,kind,item,identity,since:row.date});}
      }
    });
    const values=[...views.values()];
    for(const view of values){const repeated=values.filter(other=>other.kind===view.kind&&other.item.key===view.item.key).length>1;view.label=`${view.kind==='state'?'状态 · ':''}${view.item.label}${repeated?`（${view.since} 起）`:''}`;}
    if(values.length&&legacy)values.unshift({key:'legacy',kind:'legacy',label:'历史信号（原始值）'});
    return values;
  }
  function signalItem(observation,view){
    if(observation?.status!=='READY'||observation.definition_sha256!==view.identity)return null;
    return observation.signal_panel;
  }
  function drawSignalPanel(rows,view,{left,innerW,top,height,x}){
    const plotTop=top+25,plotBottom=top+height-17;
    const definition=view.item;
    const palette=['--signal','--position','--fill','--up','--down'];
    let series=[],y=null;
    const panels=rows.map(row=>({observation:byDate.get(row.date)?.observation,panel:signalItem(byDate.get(row.date)?.observation,view)}));
    const legend=[];
    if(view.kind==='group'){
      const seriesMap=new Map();panels.forEach(({panel})=>(panel?.series||[]).filter(item=>item.group===definition.key).forEach(item=>seriesMap.set(item.key,item)));series=[...seriesMap.values()];
      const available=panels.flatMap(({panel})=>(panel?.series||[]).filter(item=>item.group===definition.key&&item.status==='AVAILABLE'));
      const values=available.flatMap(item=>[item.value,...item.guides.map(guide=>guide.value)]);
      if(series.some(item=>item.render==='BAR'))values.push(0);
      const [low,high]=values.length?extent(values):[0,1],pad=(high-low||Math.abs(low)||1)*.1;
      y=scale(low-pad,high+pad,plotBottom,plotTop);
      if(values.length)[low,high].forEach(value=>add(el('text',{x:left+innerW+8,y:y(value)+4,class:'axis'},signalValue(value,definition))));
      for(const [seriesIndex,item] of series.entries()){
        const color=css(palette[seriesIndex%palette.length]);legend.push({label:item.label,color,description:item.description});
        let previous=null;const guidePrevious=new Map();
        panels.forEach(({observation,panel},index)=>{
          const sample=panel?.series.find(value=>value.key===item.key&&value.group===definition.key);
          if(!sample||sample.status!=='AVAILABLE'){previous=null;guidePrevious.clear();return;}
          const point=[x(index),y(sample.value)];
          const identity=`${observation.strategy?.release_hash||observation.release_hash}:${sample.segment_id??''}`;
          const title=`${rows[index].date} ${sample.label} ${signalValue(sample.value,definition)} ${definition.unit}；${sample.description}`;
          if(item.render==='BAR')add(el('rect',{x:point[0]-Math.max(1,Math.min(5,innerW/rows.length*.3)),y:Math.min(y(0),point[1]),width:Math.max(2,Math.min(10,innerW/rows.length*.6)),height:Math.max(1,Math.abs(y(0)-point[1])),fill:color,'data-signal-series':item.key,'aria-label':title}));
          else if(previous&&previous.index===index-1&&previous.identity===identity){
            const d=item.render==='STEP'?`M${previous.point[0]},${previous.point[1]} H${point[0]} V${point[1]}`:linePath([previous.point,point]);
            add(el('path',{d,fill:'none',stroke:color,'stroke-width':2,'data-signal-line':item.key}));
          }
          const dot=add(el('circle',{cx:point[0],cy:point[1],r:2.5,fill:color,'data-signal-series':item.key,'aria-label':title}));dot.appendChild(el('title',{},title));
          previous={point,index,identity};
          const currentGuideKeys=new Set();
          for(const guide of sample.guides){
            currentGuideKeys.add(guide.key);const gp=[x(index),y(guide.value)],prev=guidePrevious.get(guide.key);
            if(prev&&prev.index===index-1&&prev.identity===identity)add(el('path',{d:item.render==='STEP'?`M${prev.point[0]},${prev.point[1]} H${gp[0]} V${gp[1]}`:linePath([prev.point,gp]),fill:'none',stroke:color,'stroke-dasharray':'4 3','stroke-width':1,opacity:.6,'data-signal-guide-line':guide.key}));
            add(el('circle',{cx:gp[0],cy:gp[1],r:1.5,fill:color,'data-signal-guide':guide.key,'aria-label':`${rows[index].date} ${guide.label} ${signalValue(guide.value,definition)}`}));
            guidePrevious.set(guide.key,{point:gp,index,identity});
          }
          for(const key of guidePrevious.keys())if(!currentGuideKeys.has(key))guidePrevious.delete(key);
        });
      }
      if(!available.length)add(el('text',{x:left+8,y:(plotTop+plotBottom)/2+4,class:'axis'},'该区间没有有效数值；请选择日期查看状态'));
    }else{
      definition.options.forEach((option,index)=>legend.push({label:option.label,color:css(stateColor(index))}));
      let count=0;
      panels.forEach(({panel},index)=>{
        const sample=panel?.states.find(item=>item.key===definition.key);
        if(!sample||sample.status!=='AVAILABLE')return;
        const optionIndex=definition.options.findIndex(option=>option.key===sample.value),option=definition.options[optionIndex];
        const half=rows.length===1?Math.min(24,innerW/2):innerW/(rows.length-1)*.38;
        const start=Math.max(left,x(index)-half),end=Math.min(left+innerW,x(index)+half);
        const node=add(el('rect',{x:start,y:plotTop,width:Math.max(2,end-start),height:Math.max(2,plotBottom-plotTop),rx:2,fill:css(stateColor(optionIndex)),'data-signal-state':sample.key,'aria-label':`${rows[index].date} ${sample.label}：${option.label}`}));
        node.appendChild(el('title',{},`${rows[index].date} ${sample.label}：${option.label}；${sample.description}`));count++;
      });
      if(!count)add(el('text',{x:left+8,y:(plotTop+plotBottom)/2+4,class:'axis'},'该区间没有有效状态'));
    }
    signalLegend.replaceChildren(...legend.map(item=>{const node=document.createElement('span');node.textContent=item.label;node.style.color=item.color;node.title=item.description||item.label;return node;}));
    return {view,series,y};
  }
  function signalDetails(observation,view){
    if(observation?.status==='UNAVAILABLE')return `<div class="head">观察不可用</div><div class="signal-panel-description">${safe(observation.message)}</div>`;
    const panel=signalItem(observation,view);
    if(!panel)return '<div class="head">当日没有该声明的信号观察</div>';
    const items=view.kind==='state'?panel.states.filter(item=>item.key===view.item.key):panel.series.filter(item=>item.group===view.item.key);
    return `<div class="head">${safe(view.label)}</div><div class="grid">${items.map(item=>{
      let value=availabilityLabel(item);
      if(item.status==='AVAILABLE')value=view.kind==='state'?item.options.find(option=>option.key===item.value).label:signalValue(item.value,view.item);
      if(item.reason)value+=` · ${item.reason}`;
      const guides=item.status==='AVAILABLE'?(item.guides||[]).map(guide=>`<span>${safe(guide.label)}</span><span>${safe(signalValue(guide.value,view.item))}</span>`).join(''):'';
      return `<span title="${safe(item.description)}">${safe(item.label)}</span><span>${safe(value)}</span>${guides}`;
    }).join('')}</div><div class="signal-panel-description">${safe(view.item.description)}</div>`;
  }
  function render(){
    if(destroyed)return;
    colors.clear();
    const rows=visibleBars();
    if(!rows.length){
      const width=Math.max(320,stage.clientWidth),date=state.selected||eventDates.at(-1)||context.window.end;
      const measure=document.createElement('canvas').getContext('2d');measure.font='11px sans-serif';
      const lines=wrapExplanation(eventLines(date),width-48,measure),top=width>=1000?190:290,height=top+60+18*lines.length;
      svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.style.height=`${height}px`;stage.style.minHeight=`${height}px`;
      add(el('text',{x:18,y:25,class:'panel-label'},'没有可展示的行情；事件按原始记录展示'));
      reading.style.top='42px';reading.style.height=`${top-55}px`;paintReading(byDate.get(date)?.observation,date||'');
      state.selected=date;
      add(el('text',{x:18,y:top,class:'explain-main'},`${date||''} · 事件`));
      lines.forEach((line,index)=>add(el('text',{x:18,y:top+22+18*index,class:'explain-sub'},line)));
      return;
    }
    const width=Math.max(320,stage.clientWidth),compact=width<700;
    const left=compact?52:68,right=compact?56:72,innerW=width-left-right;
    const priceTop=26,priceH=compact?220:Math.max(220,Math.min(280,Math.round(width*.19)));
    const positionTop=priceTop+priceH+18,positionH=48;
    const signalTop=positionTop+positionH+16,signalH=width>=1000?96:230;
    reading.style.top=`${signalTop}px`;reading.style.height=`${signalH}px`;
    legacyNotice.style.top=`${signalTop+signalH-2}px`;
    const measure=document.createElement('canvas').getContext('2d');
    measure.font=`11px ${getComputedStyle(svg).fontFamily}`;
    const explanations=rows.map(row=>wrapExplanation(eventLines(row.date),innerW-24,measure));
    const selectedExplanation=wrapExplanation(eventLines(state.selected||rows.at(-1).date),innerW-24,measure);
    const explainTop=signalTop+signalH+12;
    const explainH=Math.max(60,38+18*Math.max(selectedExplanation.length,...explanations.map(lines=>lines.length))),axisTop=explainTop+explainH+8,height=axisTop+30;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.style.height=`${height}px`;stage.style.minHeight=`${height}px`;svg.replaceChildren();
    const x=index=>left+(rows.length===1?innerW/2:index/(rows.length-1)*innerW);
    const prices=rows.flatMap(row=>[Number(row.low),Number(row.high)]),[pmin,pmax]=extent(prices),pad=(pmax-pmin||pmax*.01)*.09;
    const yPrice=scale(pmin-pad,pmax+pad,priceTop+priceH,priceTop);
    const rowObservations=rows.map(row=>byDate.get(row.date)?.observation).filter(item=>item?.status==='READY');
    const latestUnavailable=rows.map(row=>({date:row.date,observation:byDate.get(row.date)?.observation})).filter(item=>item.observation?.status==='UNAVAILABLE').at(-1);
    const views=signalViews(rows),lastIdentity=rowObservations.filter(item=>item.signal_panel).at(-1)?.definition_sha256;
    if(!views.some(view=>view.key===state.signalView))state.signalView=(views.find(view=>view.kind==='group'&&view.identity===lastIdentity)||views.at(-1))?.key||null;
    const signalView=views.find(view=>view.key===state.signalView),enhanced=signalView&&signalView.kind!=='legacy';
    signalControls.hidden=!views.length||!state.layers.signal;signalLegend.hidden=!views.length||!state.layers.signal;
    signalControls.style.left=`${left}px`;signalControls.style.top=`${signalTop}px`;signalControls.style.width=`${innerW}px`;
    signalLegend.style.left=`${left}px`;signalLegend.style.top=`${signalTop+signalH-14}px`;signalLegend.style.width=`${innerW}px`;
    signalSelect.replaceChildren(...views.map(view=>{const option=document.createElement('option');option.value=view.key;option.textContent=view.label;option.title=view.item?.description||view.label;return option;}));signalSelect.value=state.signalView||'';
    signalUnit.textContent=enhanced?(signalView.kind==='group'?`${signalView.item.unit} · ${signalView.item.basis}`:signalView.item.description):'原始数值';signalUnit.title=signalUnit.textContent;
    const legacyObservations=views.length?rowObservations.filter(item=>!item.signal_panel):rowObservations;
    const allSeries=legacyObservations.flatMap(item=>item.series||[]),signalValues=allSeries.flatMap(item=>[item.value,...(item.guides||[]).map(guide=>guide.value)]);
    const [smin0,smax0]=signalValues.length?extent(signalValues):[0,1],spad=(smax0-smin0||1)*.12,ySignal=scale(smin0-spad,smax0+spad,signalTop+signalH-(views.length?17:0),signalTop+(views.length?25:0));
    const quantities=[0,...snapshots.map(item=>Number(item.quantity))];
    const qmax=Math.max(...quantities,1),yPosition=scale(0,qmax*1.08,positionTop+positionH,positionTop);
    const visibleCutoff=rows.findIndex(row=>row.date>cutoff);
    if(visibleCutoff>=0){const cutoffX=visibleCutoff?x(visibleCutoff-.5):x(0);add(el('rect',{x:cutoffX,y:priceTop,width:left+innerW-cutoffX,height:explainTop+explainH-priceTop,fill:css('--forward')}));add(el('line',{x1:cutoffX,x2:cutoffX,y1:priceTop,y2:explainTop+explainH,class:'cutoff'}));add(el('text',{x:cutoffX+6,y:priceTop+12,class:'cutoff-label'},'冻结后前瞻区间'));}
    const priceTicks=5;for(let index=0;index<priceTicks;index++){const value=pmin-pad+(pmax-pmin+2*pad)*index/(priceTicks-1),y=yPrice(value);add(el('line',{x1:left,x2:left+innerW,y1:y,y2:y,class:'grid-line'}));add(el('text',{x:left+innerW+8,y:y+4,class:'axis'},fmt(value)));}
    const priceLabel=add(el('text',{x:8,y:priceTop+12,class:'panel-label','aria-label':'价格（后复权）'},'价格'));
    priceLabel.appendChild(el('tspan',{x:8,dy:15},'后复权'));
    add(el('text',{x:12,y:signalTop+18,class:'panel-label'},'信号'));add(el('text',{x:12,y:positionTop+12,class:'panel-label'},'持仓'));add(el('text',{x:12,y:explainTop+15,class:'panel-label'},'事件'));
    const candleW=Math.max(3,Math.min(10,innerW/rows.length*.58));rows.forEach((row,index)=>{const rising=Number(row.close)>=Number(row.open),color=css(rising?'--up':'--down'),cx=x(index);add(el('line',{x1:cx,x2:cx,y1:yPrice(row.high),y2:yPrice(row.low),stroke:color,'stroke-width':1}));add(el('rect',{x:cx-candleW/2,y:yPrice(Math.max(row.open,row.close)),width:candleW,height:Math.max(1.5,Math.abs(yPrice(row.open)-yPrice(row.close))),fill:rising?color:css('--surface'),stroke:color,'stroke-width':1}));});
    const seriesKeys=[...new Set(allSeries.map(item=>item.key))];const seriesColors=['--signal','--position','--fill','--up'];
    if(state.layers.signal&&!enhanced)seriesKeys.forEach((key,seriesIndex)=>{const points=[];const guidePoints=new Map();rows.forEach((row,index)=>{const observation=byDate.get(row.date)?.observation;if(observation?.status!=='READY'||(views.length&&observation.signal_panel))return;const series=(observation.series||[]).find(item=>item.key===key);if(!series)return;points.push([x(index),ySignal(series.value),`${row.date} ${series.label} ${fmt(series.value)}`]);for(const guide of series.guides||[]){if(!guidePoints.has(guide.key))guidePoints.set(guide.key,{label:guide.label,points:[]});guidePoints.get(guide.key).points.push([x(index),ySignal(guide.value),`${row.date} ${guide.label} ${fmt(guide.value)}`]);}});const color=css(seriesColors[seriesIndex%seriesColors.length]);if(points.length>1)add(el('path',{d:linePath(points),fill:'none',stroke:color,'stroke-width':2}));points.forEach(point=>add(el('circle',{cx:point[0],cy:point[1],r:3,fill:color,'data-series-key':key,'aria-label':point[2]})));guidePoints.forEach((guide,guideKey)=>{if(guide.points.length>1)add(el('path',{d:linePath(guide.points),fill:'none',stroke:css('--fill'),'stroke-width':1,'stroke-dasharray':'4 4',opacity:.72}));guide.points.forEach(point=>add(el('circle',{cx:point[0],cy:point[1],r:2.5,fill:css('--fill'),'data-guide-key':guideKey,'aria-label':point[2]})));});});
    if(enhanced){if(state.layers.signal)drawSignalPanel(rows,signalView,{left,innerW,top:signalTop,height:signalH,x});}
    else if(!allSeries.length){
      const warning=latestUnavailable?`${latestUnavailable.date} 观察不可用：${latestUnavailable.observation.message}`:'暂无可信策略信号';
      const lines=wrapExplanation(warning,innerW-24,measure),maxLines=Math.max(1,Math.floor((signalH-16)/18));
      const node=add(el('text',{x:left+12,y:signalTop+20,class:'axis','data-signal-warning':latestUnavailable?'unavailable':'empty'},''));
      lines.slice(0,maxLines).forEach((line,index)=>node.appendChild(el('tspan',{x:left+12,dy:index?18:0},index===maxLines-1&&lines.length>maxLines?`${line.slice(0,-1)}…`:line)));
      node.appendChild(el('title',{},warning));
    }
    else if(state.layers.signal){[smin0,smax0].forEach(value=>add(el('text',{x:left+innerW+8,y:ySignal(value)+4,class:'axis'},fmt(value))));if(!views.length)seriesKeys.forEach((key,index)=>{const series=allSeries.find(item=>item.key===key);add(el('text',{x:left+index*150,y:signalTop+12,fill:css(seriesColors[index%seriesColors.length]),class:'axis'},series.label));});else signalLegend.replaceChildren(...seriesKeys.map((key,index)=>{const label=document.createElement('span');label.textContent=allSeries.find(item=>item.key===key).label;label.style.color=css(seriesColors[index%seriesColors.length]);return label;}));}
    fills.filter(item=>rows.some(row=>row.date===fillDate(item))).forEach(item=>{if(!state.layers.fill)return;const date=fillDate(item),index=rows.findIndex(row=>row.date===date),row=rows[index],buy=String(item.side).toUpperCase()==='BUY',cy=yPrice(buy?row.low:row.high)+(buy?-25:25),cx=x(index);add(el('path',{d:`M${cx},${cy} l-6,${buy?9:-9} h12 z`,fill:css('--fill'),'data-fill-id':item.fill_id}));});
    if(state.layers.position){const positionPoints=[];rows.forEach((row,index)=>{const snapshot=snapshotByDate.get(row.date);const quantity=snapshot?.quantity;if(quantity!=null)positionPoints.push([x(index),yPosition(quantity)]);});if(positionPoints.length){let d=`M${positionPoints[0][0]},${positionPoints[0][1]}`;for(let i=1;i<positionPoints.length;i++)d+=` H${positionPoints[i][0]} V${positionPoints[i][1]}`;add(el('path',{d,fill:'none',stroke:css('--position'),'stroke-width':2}));}[0,qmax].forEach(value=>add(el('text',{x:left+innerW+8,y:yPosition(value)+4,class:'axis'},value?Number(value).toLocaleString('zh-CN'):'0')));}
    [signalTop-10,positionTop-9,explainTop-9].forEach((y,index)=>{add(el('line',{x1:0,x2:width,y1:y,y2:y,class:'panel-rule'}));});add(el('rect',{x:left,y:explainTop,width:innerW,height:explainH,fill:css('--surface2')}));add(el('line',{x1:0,x2:width,y1:axisTop-4,y2:axisTop-4,class:'panel-rule'}));
    const tickCount=Math.min(rows.length,compact?4:7);for(let i=0;i<tickCount;i++){const index=tickCount===1?0:Math.round(i*(rows.length-1)/(tickCount-1));add(el('text',{x:x(index),y:axisTop+18,class:'axis','text-anchor':i===0?'start':i===tickCount-1?'end':'middle'},shortDate(rows[index].date)));}
    const cross=add(el('line',{y1:priceTop,y2:explainTop+explainH,class:'crosshair'})),priceDot=add(el('circle',{r:4,fill:css('--text'),stroke:css('--surface'),'stroke-width':2})),signalDot=add(el('circle',{r:4,fill:css('--signal'),stroke:css('--surface'),'stroke-width':2})),main=add(el('text',{x:left+12,y:explainTop+22,class:'explain-main'})),sub=add(el('text',{x:left+12,y:explainTop+42,class:'explain-sub'}));
    function showEvents(date){
      state.selected=date;paintReading(byDate.get(date)?.observation,date);
      const selectedFills=dayFills(date),selectedDecisions=dayDecisions(date);
      const event=[selectedDecisions.length?`决策 ${selectedDecisions.length} 笔`:'',selectedFills.length?`成交 ${selectedFills.length} 笔`:''].filter(Boolean).join(' · ')||'当日无可展示事件';
      main.textContent=`${date} · ${event}${tradingDates.has(date)?'':' · 非交易日，无行情K线'}`;
      sub.replaceChildren(...wrapExplanation(eventLines(date),innerW-24,measure).map((text,line)=>el('tspan',{x:left+12,dy:line?18:0,'xml:space':'preserve'},text)));
    }
    function select(index,pointer){
      index=Math.max(0,Math.min(rows.length-1,index));state.selected=rows[index].date;
      const row=rows[index],decision=byDate.get(row.date),observation=decision?.observation;
      showEvents(row.date);
      cross.style.display='';priceDot.style.display='';
      cross.setAttribute('x1',x(index));cross.setAttribute('x2',x(index));priceDot.setAttribute('cx',x(index));priceDot.setAttribute('cy',yPrice(row.close));
      const first=!enhanced&&state.layers.signal&&observation?.status==='READY'&&(!views.length||!observation.signal_panel)?observation.series?.[0]:null;
      signalDot.style.display=first?'':'none';if(first){signalDot.setAttribute('cx',x(index));signalDot.setAttribute('cy',ySignal(first.value));}
      tooltip.innerHTML=`<div class="head">${safe(row.date)}</div><div class="head">行情（后复权）</div><div class="grid"><span>开 / 高</span><span>${fmt(row.open)} / ${fmt(row.high)}</span><span>低 / 收</span><span>${fmt(row.low)} / ${fmt(row.close)}</span></div>`;
      if(enhanced&&state.layers.signal){
        const panel=signalItem(observation,signalView),items=signalView.kind==='group'?(panel?.series||[]).filter(item=>item.group===signalView.item.key):(panel?.states||[]).filter(item=>item.key===signalView.item.key);
        signalLegend.replaceChildren(...(items.length?items.map((item,index)=>{const label=document.createElement('span');const value=item.status==='AVAILABLE'?(signalView.kind==='group'?signalValue(item.value,signalView.item):item.options.find(option=>option.key===item.value).label):availabilityLabel(item);label.textContent=`${item.label}：${value}${(item.guides||[]).map(guide=>` / ${guide.label} ${signalValue(guide.value,signalView.item)}`).join('')}`;label.title=[item.description,item.reason].filter(Boolean).join('；');label.style.color=css(stateColor(signalView.kind==='state'&&item.status==='AVAILABLE'?item.options.findIndex(option=>option.key===item.value):index));return label;}):[Object.assign(document.createElement('span'),{textContent:observation?.status==='UNAVAILABLE'?`观察不可用：${observation.message}`:'当日没有该声明的信号观察',title:observation?.message||''})]));
        if(pointer&&pointer[1]>=signalTop&&pointer[1]<=signalTop+signalH)tooltip.innerHTML=`<div class="head">${safe(row.date)}</div>${signalDetails(observation,signalView)}`;
      }
      if(!enhanced&&state.layers.signal&&pointer&&pointer[1]>=signalTop&&pointer[1]<=signalTop+signalH){
        const failure=observation?.status==='UNAVAILABLE'?{date:row.date,observation}:!rowObservations.length?latestUnavailable:null;
        if(failure)tooltip.innerHTML=`<div class="head">${safe(failure.date)}</div>${signalDetails(failure.observation,null)}`;
      }
      if(pointer){
        tooltip.hidden=false;
        const tooltipWidth=tooltip.offsetWidth,leftPos=pointer[0]+18;
        tooltip.style.left=`${Math.max(0,leftPos+tooltipWidth>width?pointer[0]-tooltipWidth-18:leftPos)}px`;
        tooltip.style.top=`${Math.max(0,Math.min(height-tooltip.offsetHeight,pointer[1]-34))}px`;
      }
    }
    const selectedIndex=rows.findIndex(row=>row.date===state.selected);
    if(state.selected&&selectedIndex<0){
      showEvents(state.selected);cross.style.display='none';priceDot.style.display='none';signalDot.style.display='none';tooltip.hidden=true;
    }else select(selectedIndex<0?rows.length-1:selectedIndex,null);
    const overlay=add(el('rect',{x:left,y:priceTop,width:innerW,height:explainTop+explainH-priceTop,fill:'transparent'}));overlay.addEventListener('pointermove',event=>{const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)*width/rect.width,py=(event.clientY-rect.top)*height/rect.height,index=Math.round((px-left)/innerW*(rows.length-1));select(index,[px,py]);});overlay.addEventListener('click',event=>{const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)*width/rect.width;select(Math.round((px-left)/innerW*(rows.length-1)),null);tooltip.hidden=true;svg.focus({preventScroll:true});});overlay.addEventListener('pointerleave',()=>{tooltip.hidden=true;});
  }
  listen(svg,'keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)||!eventDates.length)return;
    event.preventDefault();
    const current=eventDates.indexOf(state.selected);
    const index=event.key==='Home'?0:event.key==='End'?eventDates.length-1:
      Math.max(0,Math.min(eventDates.length-1,(current<0?eventDates.length-1:current)+(event.key==='ArrowLeft'?-1:1)));
    state.selected=eventDates[index];tooltip.hidden=true;render();
  });
  listen(signalSelect,'change',()=>{state.signalView=signalSelect.value;tooltip.hidden=true;render();});
  root.querySelectorAll('[data-range]').forEach(button=>listen(button,'click',()=>{state.range=button.dataset.range==='all'?'all':Number(button.dataset.range);root.querySelectorAll('[data-range]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));render();}));
  root.querySelectorAll('[data-layer]').forEach(button=>listen(button,'click',()=>{const layer=button.dataset.layer;state.layers[layer]=!state.layers[layer];button.setAttribute('aria-pressed',String(state.layers[layer]));render();}));
  const viewportWindow=embedded?window.parent:window;
  listen(viewportWindow,'resize',render);
  let lastWidth=0;
  const resizeObserver=new ResizeObserver(()=>{const width=stage.clientWidth;if(width!==lastWidth){lastWidth=width;render();}});
  resizeObserver.observe(stage);
  const destroy=()=>{if(destroyed)return;destroyed=true;lifecycle.abort();resizeObserver.disconnect();reading.remove();legacyNotice.remove();signalControls.remove();signalLegend.remove();svg.replaceChildren();tooltip.hidden=true;delete root.dataset.strategyChartMounted;};
  listen(window,'pagehide',destroy);render();
  return {destroy};
};
