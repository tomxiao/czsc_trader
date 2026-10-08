(()=>{
  const root=document.querySelector('#pte-forward-chart');
  const stage=document.querySelector('#forward-stage');
  const svg=document.querySelector('#forward-svg');
  const tooltip=document.querySelector('#forward-tooltip');
  const context=JSON.parse(document.querySelector('#forward-context').textContent);
  const embedded=window.parent!==window;
  if(embedded)root.classList.add('embedded');
  const NS='http://www.w3.org/2000/svg';
  const css=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const state={range:'all',layers:{signal:true,fill:true,position:true},selected:null};
  const bars=context.market_data.bars||[];
  const invalidatedIds=new Set((context.execution.decisions||[]).filter(item=>item.status==='INVALIDATED').map(item=>item.decision_id));
  const observations=(context.observations||[]).filter(item=>!invalidatedIds.has(item.decision_id));
  const decisions=(context.execution.decisions||[]).filter(item=>item.status!=='INVALIDATED').sort((a,b)=>a.generated_at.localeCompare(b.generated_at));
  const fills=[...(context.execution.fills||[])].sort((a,b)=>Date.parse(a.occurred_at)-Date.parse(b.occurred_at));
  const snapshots=context.execution.snapshots||[];
  const cutoff=context.window.selection_data_cutoff;
  const byDate=new Map([...observations].sort((a,b)=>a.generated_at.localeCompare(b.generated_at)).map(item=>[item.signal_date,item]));
  const observationById=new Map(observations.map(item=>[item.decision_id,item.observation]));
  const snapshotByDate=new Map(snapshots.map(item=>[item.session,item]));
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
  const fillDate=item=>item.occurred_at?localTime(item.occurred_at).slice(0,10):item.session;
  const statusLabel=value=>({ACTIVE:'当前有效',SUPERSEDED:'已替代',INVALIDATED:'已失效'}[value]||value);
  const quantity=value=>value==null?'未记录':`${Number(value).toLocaleString('zh-CN')} 股`;
  const money=value=>value==null?'未记录':`${Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})} 元`;
  const dayDecisions=date=>decisions.filter(item=>item.valid_session===date);
  const dayFills=date=>fills.filter(item=>fillDate(item)===date);
  const fillSummary=item=>`成交：${String(item.side).toUpperCase()==='BUY'?'买入':'卖出'} ${quantity(item.quantity)}，价格 ${fmt(item.price)} 元（不复权），金额 ${money(Number(item.quantity)*Number(item.price))}，费用 ${money(item.fee)}；时间 ${localTime(item.occurred_at)}`;

  document.querySelector('#forward-title').textContent=`${context.strategy.release_id} · ${context.strategy.name}`;
  const observationStart=context.window.observation_start;
  document.querySelector('#forward-subtitle').textContent=`前瞻观察 · ${context.strategy.symbol} · ${context.strategy.account_id} · ${observationStart?`观察事实自 ${observationStart}`:'等待首条观察事实'}`;
  document.querySelector('#forward-asof').textContent=`运行正常 · 数据截至 ${context.market_data.as_of}`;

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
    return [...(observation.series||[]).map(item=>`${item.label} ${Number(item.value).toFixed(4)}${(item.guides||[]).map(guide=>` / ${guide.label} ${Number(guide.value).toFixed(4)}`).join('')}`),
      ...(observation.facts||[]).map(item=>`${item.label} ${factValue(item)}`)].join('；');
  }
  function eventLines(date){
    const lines=[];
    for(const item of dayDecisions(date)){
      lines.push(`决策：${actionLabel(item.action)}；目标 ${quantity(item.target_quantity)}；${statusLabel(item.status)}；生效 ${item.valid_session}；信号 ${item.signal_date}；生成 ${localTime(item.generated_at)}`);
      const observation=observationById.get(item.decision_id);
      lines.push(observation?`决策依据：${explanation(observation)}`:'决策依据：无可用于本图的策略观察事实');
    }
    lines.push(...dayFills(date).map(fillSummary));
    if(!lines.length)lines.push('当日无可展示的决策或成交事件');
    return lines.join('\n');
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
  function render(){
    const rows=visibleBars();if(!rows.length)return;
    const width=Math.max(320,stage.clientWidth),compact=width<700;
    const left=compact?52:68,right=compact?56:72,innerW=width-left-right;
    const priceTop=34,priceH=embedded?Math.max(180,Math.min(285,window.parent.innerHeight-540)):(compact?250:285),signalTop=priceTop+priceH+20,signalH=embedded?70:(compact?92:105);
    const positionTop=signalTop+signalH+18,positionH=compact?0:(embedded?50:68);
    const measure=document.createElement('canvas').getContext('2d');
    measure.font=`11px ${getComputedStyle(svg).fontFamily}`;
    const explanations=rows.map(row=>wrapExplanation(eventLines(row.date),innerW-24,measure));
    const explainTop=compact?positionTop+12:positionTop+positionH+18;
    const explainH=Math.max(62,44+18*Math.max(...explanations.map(lines=>lines.length))),axisTop=explainTop+explainH+8,height=axisTop+30;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.style.height=`${height}px`;stage.style.minHeight=`${height}px`;svg.replaceChildren();
    const x=index=>left+(rows.length===1?innerW/2:index/(rows.length-1)*innerW);
    const prices=rows.flatMap(row=>[Number(row.low),Number(row.high)]),[pmin,pmax]=extent(prices),pad=(pmax-pmin||pmax*.01)*.09;
    const yPrice=scale(pmin-pad,pmax+pad,priceTop+priceH,priceTop);
    const rowObservations=rows.map(row=>byDate.get(row.date)?.observation).filter(item=>item?.status==='READY');
    const allSeries=rowObservations.flatMap(item=>item.series||[]),signalValues=allSeries.flatMap(item=>[item.value,...(item.guides||[]).map(guide=>guide.value)]);
    const [smin0,smax0]=signalValues.length?extent(signalValues):[0,1],spad=(smax0-smin0||1)*.12,ySignal=scale(smin0-spad,smax0+spad,signalTop+signalH,signalTop);
    const quantities=[0,...snapshots.map(item=>Number(item.quantity))];
    const qmax=Math.max(...quantities,1),yPosition=scale(0,qmax*1.08,positionTop+positionH,positionTop);
    const visibleCutoff=rows.findIndex(row=>row.date>cutoff);
    if(visibleCutoff>=0){const cutoffX=visibleCutoff?x(visibleCutoff-.5):x(0);add(el('rect',{x:cutoffX,y:priceTop,width:left+innerW-cutoffX,height:explainTop+explainH-priceTop,fill:css('--forward')}));add(el('line',{x1:cutoffX,x2:cutoffX,y1:priceTop,y2:explainTop+explainH,class:'cutoff'}));add(el('text',{x:cutoffX+6,y:priceTop+12,class:'cutoff-label'},'冻结后前瞻区间'));}
    const priceTicks=5;for(let index=0;index<priceTicks;index++){const value=pmin-pad+(pmax-pmin+2*pad)*index/(priceTicks-1),y=yPrice(value);add(el('line',{x1:left,x2:left+innerW,y1:y,y2:y,class:'grid-line'}));add(el('text',{x:left+innerW+8,y:y+4,class:'axis'},fmt(value)));}
    const priceLabel=add(el('text',{x:8,y:priceTop+12,class:'panel-label','aria-label':'价格（后复权）'},'价格'));
    priceLabel.appendChild(el('tspan',{x:8,dy:15},'后复权'));
    add(el('text',{x:12,y:signalTop+12,class:'panel-label'},'信号'));if(!compact)add(el('text',{x:12,y:positionTop+12,class:'panel-label'},'持仓'));add(el('text',{x:12,y:explainTop+15,class:'panel-label'},'事件'));
    const candleW=Math.max(3,Math.min(10,innerW/rows.length*.58));rows.forEach((row,index)=>{const rising=Number(row.close)>=Number(row.open),color=css(rising?'--up':'--down'),cx=x(index);add(el('line',{x1:cx,x2:cx,y1:yPrice(row.high),y2:yPrice(row.low),stroke:color,'stroke-width':1}));add(el('rect',{x:cx-candleW/2,y:yPrice(Math.max(row.open,row.close)),width:candleW,height:Math.max(1.5,Math.abs(yPrice(row.open)-yPrice(row.close))),fill:rising?color:css('--surface'),stroke:color,'stroke-width':1}));});
    const seriesKeys=[...new Set(allSeries.map(item=>item.key))];const seriesColors=['--signal','--position','--fill','--up'];
    if(state.layers.signal)seriesKeys.forEach((key,seriesIndex)=>{const points=[];const guidePoints=new Map();rows.forEach((row,index)=>{const observation=byDate.get(row.date)?.observation;if(observation?.status!=='READY')return;const series=(observation.series||[]).find(item=>item.key===key);if(!series)return;points.push([x(index),ySignal(series.value),`${row.date} ${series.label} ${fmt(series.value)}`]);for(const guide of series.guides||[]){if(!guidePoints.has(guide.key))guidePoints.set(guide.key,{label:guide.label,points:[]});guidePoints.get(guide.key).points.push([x(index),ySignal(guide.value),`${row.date} ${guide.label} ${fmt(guide.value)}`]);}});const color=css(seriesColors[seriesIndex%seriesColors.length]);if(points.length>1)add(el('path',{d:linePath(points),fill:'none',stroke:color,'stroke-width':2}));points.forEach(point=>add(el('circle',{cx:point[0],cy:point[1],r:3,fill:color,'data-series-key':key,'aria-label':point[2]})));guidePoints.forEach((guide,guideKey)=>{if(guide.points.length>1)add(el('path',{d:linePath(guide.points),fill:'none',stroke:css('--fill'),'stroke-width':1,'stroke-dasharray':'4 4',opacity:.72}));guide.points.forEach(point=>add(el('circle',{cx:point[0],cy:point[1],r:2.5,fill:css('--fill'),'data-guide-key':guideKey,'aria-label':point[2]})));});});
    if(!allSeries.length)add(el('text',{x:left+12,y:signalTop+signalH/2,class:'axis'},'暂无可信策略信号'));
    else if(state.layers.signal){[smin0,smax0].forEach(value=>add(el('text',{x:left+innerW+8,y:ySignal(value)+4,class:'axis'},fmt(value))));seriesKeys.forEach((key,index)=>{const series=allSeries.find(item=>item.key===key);add(el('text',{x:left+index*150,y:signalTop+12,fill:css(seriesColors[index%seriesColors.length]),class:'axis'},series.label));});}
    fills.filter(item=>rows.some(row=>row.date===fillDate(item))).forEach(item=>{if(!state.layers.fill)return;const date=fillDate(item),index=rows.findIndex(row=>row.date===date),row=rows[index],buy=String(item.side).toUpperCase()==='BUY',cy=yPrice(buy?row.low:row.high)+(buy?-25:25),cx=x(index);add(el('path',{d:`M${cx},${cy} l-6,${buy?9:-9} h12 z`,fill:css('--fill'),'data-fill-id':item.fill_id}));});
    if(!compact&&state.layers.position){const positionPoints=[];rows.forEach((row,index)=>{const snapshot=snapshotByDate.get(row.date);const quantity=snapshot?.quantity;if(quantity!=null)positionPoints.push([x(index),yPosition(quantity)]);});if(positionPoints.length){let d=`M${positionPoints[0][0]},${positionPoints[0][1]}`;for(let i=1;i<positionPoints.length;i++)d+=` H${positionPoints[i][0]} V${positionPoints[i][1]}`;add(el('path',{d,fill:'none',stroke:css('--position'),'stroke-width':2}));}[0,qmax].forEach(value=>add(el('text',{x:left+innerW+8,y:yPosition(value)+4,class:'axis'},value?Number(value).toLocaleString('zh-CN'):'0')));}
    [signalTop-10,positionTop-9,explainTop-9].forEach((y,index)=>{if(compact&&index===1)return;add(el('line',{x1:0,x2:width,y1:y,y2:y,class:'panel-rule'}));});add(el('rect',{x:left,y:explainTop,width:innerW,height:explainH,fill:css('--surface2')}));add(el('line',{x1:0,x2:width,y1:axisTop-4,y2:axisTop-4,class:'panel-rule'}));
    const tickCount=compact?4:7;for(let i=0;i<tickCount;i++){const index=Math.round(i*(rows.length-1)/(tickCount-1));add(el('text',{x:x(index),y:axisTop+18,class:'axis','text-anchor':i===0?'start':i===tickCount-1?'end':'middle'},shortDate(rows[index].date)));}
    const cross=add(el('line',{y1:priceTop,y2:explainTop+explainH,class:'crosshair'})),priceDot=add(el('circle',{r:4,fill:css('--text'),stroke:css('--surface'),'stroke-width':2})),signalDot=add(el('circle',{r:4,fill:css('--signal'),stroke:css('--surface'),'stroke-width':2})),main=add(el('text',{x:left+12,y:explainTop+22,class:'explain-main'})),sub=add(el('text',{x:left+12,y:explainTop+42,class:'explain-sub'}));
    function select(index,pointer){
      index=Math.max(0,Math.min(rows.length-1,index));state.selected=rows[index].date;
      const row=rows[index],decision=byDate.get(row.date),observation=decision?.observation;
      const selectedFills=dayFills(row.date),selectedDecisions=dayDecisions(row.date);
      cross.setAttribute('x1',x(index));cross.setAttribute('x2',x(index));priceDot.setAttribute('cx',x(index));priceDot.setAttribute('cy',yPrice(row.close));
      const first=observation?.status==='READY'?observation.series?.[0]:null;
      signalDot.style.display=first?'':'none';if(first){signalDot.setAttribute('cx',x(index));signalDot.setAttribute('cy',ySignal(first.value));}
      const event=[selectedDecisions.length?`决策 ${selectedDecisions.length} 笔`:'',selectedFills.length?`成交 ${selectedFills.length} 笔`:''].filter(Boolean).join(' · ')||'当日无可展示事件';
      main.textContent=`${row.date} · ${event}`;
      sub.replaceChildren(...explanations[index].map((text,line)=>el('tspan',{x:left+12,dy:line?18:0,'xml:space':'preserve'},text)));
      tooltip.innerHTML=`<div class="head">${safe(row.date)}</div><div class="head">行情（后复权）</div><div class="grid"><span>开 / 高</span><span>${fmt(row.open)} / ${fmt(row.high)}</span><span>低 / 收</span><span>${fmt(row.low)} / ${fmt(row.close)}</span></div>`;
      if(pointer){
        tooltip.hidden=false;
        const tooltipWidth=tooltip.offsetWidth,leftPos=pointer[0]+18;
        tooltip.style.left=`${Math.max(0,leftPos+tooltipWidth>width?pointer[0]-tooltipWidth-18:leftPos)}px`;
        tooltip.style.top=`${Math.max(0,Math.min(height-tooltip.offsetHeight,pointer[1]-34))}px`;
      }
    }
    const selectedIndex=rows.findIndex(row=>row.date===state.selected);
    select(selectedIndex<0?rows.length-1:selectedIndex,null);
    const overlay=add(el('rect',{x:left,y:priceTop,width:innerW,height:explainTop+explainH-priceTop,fill:'transparent'}));overlay.addEventListener('pointermove',event=>{const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)*width/rect.width,py=(event.clientY-rect.top)*height/rect.height,index=Math.round((px-left)/innerW*(rows.length-1));select(index,[px,py]);});overlay.addEventListener('pointerleave',()=>{tooltip.hidden=true;});
  }
  document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{state.range=button.dataset.range==='all'?'all':Number(button.dataset.range);document.querySelectorAll('[data-range]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));render();}));
  document.querySelectorAll('[data-layer]').forEach(button=>button.addEventListener('click',()=>{const layer=button.dataset.layer;state.layers[layer]=!state.layers[layer];button.setAttribute('aria-pressed',String(state.layers[layer]));render();}));
  const viewportWindow=embedded?window.parent:window;
  viewportWindow.addEventListener('resize',render);
  window.addEventListener('pagehide',()=>viewportWindow.removeEventListener('resize',render),{once:true});
  new ResizeObserver(render).observe(stage);render();
})();
