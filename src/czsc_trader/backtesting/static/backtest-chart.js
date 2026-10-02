(()=>{
  const root=document.querySelector('#tdr-backtest-chart');
  const stage=document.querySelector('#forward-stage');
  const svg=document.querySelector('#forward-svg');
  const tooltip=document.querySelector('#forward-tooltip');
  const context=JSON.parse(document.querySelector('#forward-context').textContent);
  const NS='http://www.w3.org/2000/svg';
  const css=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const state={range:40,layers:{signal:true,fill:true,position:true},selected:null};
  const bars=context.market_data.bars||[];
  const observations=context.observations||[];
  const fills=context.execution.fills||[];
  const snapshots=context.execution.snapshots||[];
  const byDate=new Map(observations.map(item=>[item.signal_date,item]));
  const snapshotByDate=new Map(snapshots.map(item=>[item.session,item]));
  const fmt=value=>Number(value).toLocaleString('zh-CN',{minimumFractionDigits:3,maximumFractionDigits:4});
  const shortDate=value=>String(value).slice(5);
  const actionLabel=value=>({BUY:'入场',ENTER:'入场',SELL:'退出',EXIT:'退出',HOLD:'持有',WAIT:'等待',HOLD_POSITION:'持有',HOLD_CASH:'空仓观察',NO_EVENT:'无新增事件',INTRADAY_LONG_OVERLAY:'日内增强'}[String(value).toUpperCase()]||String(value||'无新增事件'));
  const el=(name,attrs={},text='')=>{const node=document.createElementNS(NS,name);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value)));if(text)node.textContent=text;return node;};
  const linePath=points=>points.map((point,index)=>`${index?'L':'M'}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(' ');
  const extent=values=>[Math.min(...values),Math.max(...values)];
  const scale=(domainMin,domainMax,rangeMin,rangeMax)=>value=>rangeMin+(Number(value)-domainMin)/(domainMax-domainMin||1)*(rangeMax-rangeMin);
  const safe=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

  document.querySelector('#forward-title').textContent=`${context.strategy.reference_id} · ${context.strategy.symbol}`;
  document.querySelector('#forward-subtitle').textContent=`回测复盘 · ${context.window.start} — ${context.window.end} · 后复权K线`;
  document.querySelector('#forward-asof').textContent=`回测完成 · 数据截至 ${context.market_data.as_of}`;

  function visibleBars(){if(state.range==='all')return bars;return bars.slice(Math.max(0,bars.length-Number(state.range)));}
  function add(node){svg.appendChild(node);return node;}
  function render(){
    const rows=visibleBars();if(!rows.length)return;
    const width=Math.max(320,stage.clientWidth),compact=width<700;
    const left=compact?52:68,right=compact?56:72,innerW=width-left-right;
    const priceTop=34,priceH=compact?250:285,signalTop=priceTop+priceH+20,signalH=compact?92:105;
    const positionTop=signalTop+signalH+18,positionH=compact?0:68;
    const explainTop=compact?positionTop+12:positionTop+positionH+18,explainH=62,axisTop=explainTop+explainH+8,height=axisTop+30;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.style.height=`${height}px`;stage.style.minHeight=`${height}px`;svg.replaceChildren();
    const x=index=>left+(rows.length===1?innerW/2:index/(rows.length-1)*innerW);
    const prices=rows.flatMap(row=>[Number(row.low),Number(row.high)]),[pmin,pmax]=extent(prices),pad=(pmax-pmin||pmax*.01)*.09;
    const yPrice=scale(pmin-pad,pmax+pad,priceTop+priceH,priceTop);
    const rowObservations=rows.map(row=>byDate.get(row.date)?.observation).filter(item=>item?.status==='READY');
    const allSeries=rowObservations.flatMap(item=>item.series||[]),signalValues=allSeries.flatMap(item=>[item.value,...(item.guides||[]).map(guide=>guide.value)]);
    const [smin0,smax0]=signalValues.length?extent(signalValues):[0,1],spad=(smax0-smin0||1)*.12,ySignal=scale(smin0-spad,smax0+spad,signalTop+signalH,signalTop);
    const quantities=[0,...snapshots.map(item=>Number(item.quantity))];
    const qmax=Math.max(...quantities,1),yPosition=scale(0,qmax*1.08,positionTop+positionH,positionTop);
    const priceTicks=5;for(let index=0;index<priceTicks;index++){const value=pmin-pad+(pmax-pmin+2*pad)*index/(priceTicks-1),y=yPrice(value);add(el('line',{x1:left,x2:left+innerW,y1:y,y2:y,class:'grid-line'}));add(el('text',{x:left+innerW+8,y:y+4,class:'axis'},fmt(value)));}
    add(el('text',{x:12,y:priceTop+12,class:'panel-label'},'价格'));add(el('text',{x:12,y:signalTop+12,class:'panel-label'},'信号'));if(!compact)add(el('text',{x:12,y:positionTop+12,class:'panel-label'},'持仓'));add(el('text',{x:12,y:explainTop+15,class:'panel-label'},'解释'));
    const candleW=Math.max(3,Math.min(10,innerW/rows.length*.58));rows.forEach((row,index)=>{const rising=Number(row.close)>=Number(row.open),color=css(rising?'--up':'--down'),cx=x(index);add(el('line',{x1:cx,x2:cx,y1:yPrice(row.high),y2:yPrice(row.low),stroke:color,'stroke-width':1}));add(el('rect',{x:cx-candleW/2,y:yPrice(Math.max(row.open,row.close)),width:candleW,height:Math.max(1.5,Math.abs(yPrice(row.open)-yPrice(row.close))),fill:rising?color:css('--surface'),stroke:color,'stroke-width':1}));});
    const seriesKeys=[...new Set(allSeries.map(item=>item.key))];const seriesColors=['--signal','--position','--fill','--up'];
    if(state.layers.signal)seriesKeys.forEach((key,seriesIndex)=>{const points=[];const guidePoints=new Map();rows.forEach((row,index)=>{const observation=byDate.get(row.date)?.observation;if(observation?.status!=='READY')return;const series=(observation.series||[]).find(item=>item.key===key);if(!series)return;points.push([x(index),ySignal(series.value)]);for(const guide of series.guides||[]){if(!guidePoints.has(guide.key))guidePoints.set(guide.key,{label:guide.label,points:[]});guidePoints.get(guide.key).points.push([x(index),ySignal(guide.value)]);}});if(points.length)add(el('path',{d:linePath(points),fill:'none',stroke:css(seriesColors[seriesIndex%seriesColors.length]),'stroke-width':2}));guidePoints.forEach(guide=>{if(guide.points.length)add(el('path',{d:linePath(guide.points),fill:'none',stroke:css('--fill'),'stroke-width':1,'stroke-dasharray':'4 4',opacity:.72}));});});
    observations.filter(item=>rows.some(row=>row.date===item.signal_date)).forEach(item=>{const action=String(item.action).toUpperCase(),signalActions=['BUY','ENTER','SELL','EXIT','ROTATE','INTRADAY_LONG_OVERLAY'];if(!state.layers.signal||!signalActions.includes(action))return;const index=rows.findIndex(row=>row.date===item.signal_date),row=rows[index],up=['BUY','ENTER','ROTATE','INTRADAY_LONG_OVERLAY'].includes(action),cy=yPrice(up?row.low:row.high)+(up?-14:14);add(el('circle',{cx:x(index),cy,r:5,fill:css('--signal'),stroke:css('--surface'),'stroke-width':2}));if(width>620)add(el('text',{x:x(index)+7,y:cy+(up?-8:14),class:'event-label'},actionLabel(item.action)));});
    fills.filter(item=>rows.some(row=>row.date===String(item.occurred_at||item.session).slice(0,10))).forEach(item=>{if(!state.layers.fill)return;const date=String(item.occurred_at||item.session).slice(0,10),index=rows.findIndex(row=>row.date===date),row=rows[index],buy=String(item.side).toUpperCase()==='BUY',cy=yPrice(buy?row.low:row.high)+(buy?-25:25),cx=x(index);add(el('path',{d:`M${cx},${cy} l-6,${buy?9:-9} h12 z`,fill:css('--fill')}));});
    if(!compact&&state.layers.position){const positionPoints=[];rows.forEach((row,index)=>{const snapshot=snapshotByDate.get(row.date);const quantity=snapshot?.quantity;if(quantity!=null)positionPoints.push([x(index),yPosition(quantity)]);});if(positionPoints.length){let d=`M${positionPoints[0][0]},${positionPoints[0][1]}`;for(let i=1;i<positionPoints.length;i++)d+=` H${positionPoints[i][0]} V${positionPoints[i][1]}`;add(el('path',{d,fill:'none',stroke:css('--position'),'stroke-width':2}));}[0,qmax].forEach(value=>add(el('text',{x:left+innerW+8,y:yPosition(value)+4,class:'axis'},value?Number(value).toLocaleString('zh-CN'):'0')));}
    [signalTop-10,positionTop-9,explainTop-9].forEach((y,index)=>{if(compact&&index===1)return;add(el('line',{x1:0,x2:width,y1:y,y2:y,class:'panel-rule'}));});add(el('rect',{x:left,y:explainTop,width:innerW,height:explainH,fill:css('--surface2')}));add(el('line',{x1:0,x2:width,y1:axisTop-4,y2:axisTop-4,class:'panel-rule'}));
    const tickCount=compact?4:7;for(let i=0;i<tickCount;i++){const index=Math.round(i*(rows.length-1)/(tickCount-1));add(el('text',{x:x(index),y:axisTop+18,class:'axis','text-anchor':i===0?'start':i===tickCount-1?'end':'middle'},shortDate(rows[index].date)));}
    const cross=add(el('line',{y1:priceTop,y2:explainTop+explainH,class:'crosshair'})),priceDot=add(el('circle',{r:4,fill:css('--text'),stroke:css('--surface'),'stroke-width':2})),signalDot=add(el('circle',{r:4,fill:css('--signal'),stroke:css('--surface'),'stroke-width':2})),main=add(el('text',{x:left+12,y:explainTop+22,class:'explain-main'})),sub=add(el('text',{x:left+12,y:explainTop+42,class:'explain-sub'}));
    function select(index,pointer){index=Math.max(0,Math.min(rows.length-1,index));state.selected=rows[index].date;const row=rows[index],decision=byDate.get(row.date),observation=decision?.observation;cross.setAttribute('x1',x(index));cross.setAttribute('x2',x(index));priceDot.setAttribute('cx',x(index));priceDot.setAttribute('cy',yPrice(row.close));const first=observation?.status==='READY'?observation.series?.[0]:null;signalDot.style.display=first?'':'none';if(first){signalDot.setAttribute('cx',x(index));signalDot.setAttribute('cy',ySignal(first.value));}const event=decision?actionLabel(decision.action):'无新增事件';main.textContent=`${row.date} · ${event}`;const facts=observation?.status==='READY'?(observation.series||[]).map(item=>`${item.label} ${Number(item.value).toFixed(4)}${(item.guides||[]).map(guide=>` / ${guide.label} ${Number(guide.value).toFixed(4)}`).join('')}`).join('；'):observation?.message||'当日没有策略观察事实';sub.textContent=facts.length>92?`${facts.slice(0,92)}…`:facts;tooltip.innerHTML=`<div class="head"><span>${safe(row.date)}</span><span>${safe(event)}</span></div><div class="grid"><span>开 / 高</span><span>${fmt(row.open)} / ${fmt(row.high)}</span><span>低 / 收</span><span>${fmt(row.low)} / ${fmt(row.close)}</span><span>目标仓位</span><span>${decision?`${(Number(decision.observation.target_position)*100).toFixed(0)}%`:"无信号记录"}</span><span>实际持仓</span><span>${snapshotByDate.has(row.date)?`${Number(snapshotByDate.get(row.date).quantity).toLocaleString('zh-CN')} 股`:"无账户记录"}</span><span>执行日</span><span>${safe(decision?.valid_session||"无信号记录")}</span>${fills.filter(item=>item.session===row.date).map(item=>`<span>${safe(item.side==='BUY'?'买入':'卖出')}成交</span><span>${fmt(item.price)} × ${Number(item.quantity).toLocaleString('zh-CN')}股<br>未复权 · ${safe(item.occurred_at.slice(11))}</span>`).join('')}</div>`;if(pointer){tooltip.hidden=false;const tooltipWidth=250,leftPos=pointer[0]+18;tooltip.style.left=`${leftPos+tooltipWidth>width?pointer[0]-tooltipWidth-18:leftPos}px`;tooltip.style.top=`${Math.max(18,Math.min(height-175,pointer[1]-34))}px`;}}
    const selectedIndex=rows.findIndex(row=>row.date===state.selected);
    select(selectedIndex<0?rows.length-1:selectedIndex,null);
    const overlay=add(el('rect',{x:left,y:priceTop,width:innerW,height:explainTop+explainH-priceTop,fill:'transparent'}));overlay.addEventListener('pointermove',event=>{const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)*width/rect.width,py=(event.clientY-rect.top)*height/rect.height,index=Math.round((px-left)/innerW*(rows.length-1));select(index,[px,py]);});overlay.addEventListener('pointerleave',()=>{tooltip.hidden=true;});
  }
  document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{state.range=button.dataset.range==='all'?'all':Number(button.dataset.range);document.querySelectorAll('[data-range]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));render();}));
  document.querySelectorAll('[data-layer]').forEach(button=>button.addEventListener('click',()=>{const layer=button.dataset.layer;state.layers[layer]=!state.layers[layer];button.setAttribute('aria-pressed',String(state.layers[layer]));render();}));
  new ResizeObserver(render).observe(stage);render();
})();
