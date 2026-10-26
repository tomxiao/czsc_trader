import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

class Element {
  constructor(name){this.name=name;this.attributes={};this.children=[];this.style={};this.listeners={};this.dataset={};this.classList={add(){}};this.clientWidth=1000;}
  setAttribute(key,value){this.attributes[key]=value;}
  appendChild(node){node.parent=this;this.children.push(node);return node;}
    append(...nodes){nodes.forEach(node=>this.appendChild(node));}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(node=>node!==this);}
    get options(){return this.children;}
  replaceChildren(...nodes){this.children=nodes;this._text='';}
  addEventListener(name,handler){this.listeners[name]=handler;}
  set textContent(value){this._text=value;this.children=[];}
  get textContent(){return (this._text||'')+this.children.map(node=>node.textContent).join('');}
  getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:800};}
}

function snapshot(index,{segment='first',status='AVAILABLE',release='a',definition='b'}={}){
  const group={key:'condition',label:'入场条件',unit:'%',basis:'相对变化',format:'PERCENT',precision:2,description:'价格距离参考中心的空间'};
  const sample=(key,render)=>({key,label:key,group:'condition',render,description:'策略明确声明的观察值',
    value:status==='AVAILABLE'?.01*(index+1):null,status,reason:status==='UNAVAILABLE'?'缺少数据':null,
    segment_id:status==='AVAILABLE'?segment:null,guides:status==='AVAILABLE'?[{key:'threshold',label:'最低门槛',value:.015}]:[]});
  return {status:'READY',series:[{key:'legacy',label:'旧事件说明',value:.42,guides:[]}],facts:[],definition_sha256:definition.repeat(64),release_hash:release.repeat(64),
    signal_panel:{groups:[group],series:[sample('line','LINE'),sample('step','STEP'),sample('bar','BAR')],
      states:[{key:'opportunity',label:'机会状态',description:'模型机会，与成交状态独立',options:[{key:'active',label:'有效'},{key:'inactive',label:'未激活'}],
        value:status==='UNAVAILABLE'?null:index%2?'active':'inactive',status:status==='UNAVAILABLE'?'UNAVAILABLE':'AVAILABLE',reason:status==='UNAVAILABLE'?'缺少数据':null}]} };
}

function render({width=1000,observations}={}){
  const nodes=Object.fromEntries(['pte-forward-chart','forward-stage','forward-svg','forward-tooltip','forward-context','forward-title','forward-subtitle','forward-asof','forward-event-date'].map(id=>[id,new Element(id)]));
  nodes['forward-stage'].clientWidth=width;nodes['forward-svg'].clientWidth=width;
  const dates=Array.from({length:10},(_,i)=>`2026-09-${String(i+1).padStart(2,'0')}`);
  const samples=observations||[
    snapshot(0),snapshot(1),snapshot(2,{status:'INACTIVE'}),snapshot(3),snapshot(4,{segment:'second'}),
    null,snapshot(6,{segment:'second'}),snapshot(7,{segment:'second',release:'c'}),snapshot(8,{segment:'second',release:'c'}),
    snapshot(9,{definition:'d'}),
  ];
  const context={mode:'PAPER',strategy:{release_id:'S900-v1',name:'独立合成策略',symbol:'588080.SH',account_id:'test'},
    window:{selection_data_cutoff:dates[0],observation_start:dates[0]},
    market_data:{as_of:dates.at(-1),bars:dates.map(date=>({date,open:1,high:1.1,low:.9,close:1}))},
    observations:samples.flatMap((observation,i)=>observation?[{decision_id:`d${i}`,signal_date:dates[i],valid_session:'2026-09-11',generated_at:`${dates[i]}T12:30:00Z`,observation}]:[]),
    execution:{decisions:[{decision_id:'d9',signal_date:dates[9],valid_session:'2026-09-11',generated_at:`${dates[9]}T12:30:00Z`,action:'WAIT',status:'COMPLETED',target_quantity:0}],fills:[],snapshots:[]}};
  nodes['forward-context'].textContent=JSON.stringify(context);
  nodes['pte-forward-chart'].querySelector=selector=>nodes[selector.slice(1)];
  nodes['pte-forward-chart'].querySelectorAll=()=>[];
  const window={addEventListener(){},removeEventListener(){}};window.parent=window;
  runInNewContext(readFileSync(new URL('../../../strategy_chart/src/strategy_chart/static/strategy-chart.js',import.meta.url),'utf8'),{
    window,HTMLElement:Element,AbortController,document:{documentElement:new Element('html'),querySelector:selector=>nodes[selector.slice(1)],querySelectorAll:()=>[],
      createElement:name=>name==='canvas'?({getContext:()=>({measureText:text=>({width:text.length*7})})}):new Element(name),createElementNS:(_ns,name)=>new Element(name)},
    getComputedStyle:()=>({fontFamily:'sans-serif',getPropertyValue:name=>name}),ResizeObserver:class{observe(){}disconnect(){}},
  });
  window.mountStrategyChart(nodes['pte-forward-chart'],context);
  const controls=nodes['forward-stage'].children.find(node=>node.className==='signal-panel-controls');
  const select=controls.children[0],svg=nodes['forward-svg'];
  function choose(value){select.value=value;select.listeners.change();}
  return {nodes,svg,controls,select,choose};
}

test('v3 signal groups preserve gaps, segments and release boundaries while rendering all numeric styles',()=>{
  const {svg,controls,select,choose,nodes}=render();
  assert.equal(controls.hidden,false);
  assert.equal(svg.children.filter(node=>node.attributes['data-signal-series']==='line').length,1,'latest definition selected without merging old units');
  const beforeHeight=svg.attributes.viewBox;
  const beforeCandles=svg.children.filter(node=>node.name==='rect'&&node.attributes.stroke).map(node=>({...node.attributes}));
  choose(`${'b'.repeat(64)}:group:condition`);
  assert.equal(svg.children.filter(node=>node.attributes['data-signal-line']==='line').length,2);
  const steps=svg.children.filter(node=>node.attributes['data-signal-line']==='step');
  assert.equal(steps.length,2);assert.ok(steps.every(node=>/ H.* V/.test(node.attributes.d)));
  assert.equal(svg.children.filter(node=>node.name==='rect'&&node.attributes['data-signal-series']==='bar').length,7);
  assert.equal(svg.children.filter(node=>node.name==='circle'&&node.attributes['data-signal-series']==='line').length,7);
  assert.match(svg.children.find(node=>node.attributes['data-signal-series']==='line').attributes['aria-label'],/1\.00%/);
  assert.equal(svg.children.filter(node=>node.attributes['data-signal-guide-line']==='threshold').length,6);
  assert.equal(svg.attributes.viewBox,beforeHeight);
  assert.deepEqual(svg.children.filter(node=>node.name==='rect'&&node.attributes.stroke).map(node=>({...node.attributes})),beforeCandles);
  assert.match(controls.textContent,/% · 相对变化/);
  assert.match(svg.textContent,/旧事件说明 0.4200/,'event explanation remains unchanged');
  const overlay=svg.children.at(-1);
  overlay.listeners.pointermove({clientX:68+(1000-68-72)*2/9,clientY:(Number.parseFloat(controls.style.top)+35)*800/Number(svg.attributes.viewBox.split(' ')[3])});
  assert.match(nodes['forward-tooltip'].innerHTML,/当前不适用/);
  assert.doesNotMatch(nodes['forward-tooltip'].innerHTML,/行情（后复权）/);
  assert.doesNotMatch(nodes['forward-tooltip'].innerHTML,/0\.00%/);
  assert.ok(select.children.some(option=>option.textContent.includes('状态 · 机会状态')));
});

test('signal states, missing evidence and compact legends fit the same signal region',()=>{
  const samples=[snapshot(0),snapshot(1),snapshot(2,{status:'UNAVAILABLE'})];
  const {svg,controls,choose,nodes}=render({width:360,observations:samples});
  const originalHeight=svg.attributes.viewBox;
  choose(`${'b'.repeat(64)}:state:opportunity`);
  assert.equal(svg.children.filter(node=>node.attributes['data-signal-state']==='opportunity').length,2);
  assert.equal(svg.children.filter(node=>node.attributes['data-signal-series']).length,0);
  assert.equal(svg.attributes.viewBox,originalHeight);
  assert.equal(controls.style.width,'252px');
  const overlay=svg.children.at(-1);
  overlay.listeners.pointermove({clientX:52+252*2/9,clientY:(Number.parseFloat(nodes['forward-stage'].children.find(node=>node.className==='signal-panel-controls').style.top)+35)*800/Number(svg.attributes.viewBox.split(' ')[3])});
  assert.match(nodes['forward-tooltip'].innerHTML,/数据不可用.*缺少数据/);
  assert.ok(!svg.children.some(node=>Object.values(node.attributes).some(value=>String(value).includes('NaN'))));
  const css=readFileSync(new URL('../../../strategy_chart/src/strategy_chart/static/strategy-chart.css',import.meta.url),'utf8');
  assert.match(css,/\.signal-panel-legend\{[^}]*overflow-x:auto/);
  assert.match(css,/\.signal-panel-unit\{[^}]*text-overflow:ellipsis/);
});

test('whole-window observation failures show a reason without fabricated values',()=>{
  const failure={status:'UNAVAILABLE',message:'观察计算失败：历史字段缺失 <unsafe>'};
  const {svg,controls,nodes}=render({width:360,observations:Array(10).fill(failure)});
  assert.equal(controls.hidden,true);
  assert.match(svg.textContent,/观察不可用：观察计算失败/);
  assert.equal(svg.children.filter(node=>node.attributes['data-signal-series']||node.attributes['data-series-key']).length,0);
  svg.children.at(-1).listeners.pointermove({clientX:304,clientY:(Number.parseFloat(nodes['forward-stage'].children.find(node=>node.className==='signal-panel-controls').style.top)+35)*800/Number(svg.attributes.viewBox.split(' ')[3])});
  assert.match(nodes['forward-tooltip'].innerHTML,/历史字段缺失 &lt;unsafe&gt;/);
  assert.doesNotMatch(nodes['forward-tooltip'].innerHTML,/0\.00|行情（后复权）/);
});

test('current observation failure clears the legend and exposes its reason while retaining history',()=>{
  const failure={status:'UNAVAILABLE',message:'观察计算失败：行情缺日'};
  const samples=Array.from({length:10},(_,i)=>i===8?failure:snapshot(i));
  samples[9]=failure;
  const {svg,nodes,controls}=render({observations:samples});
  const legend=nodes['forward-stage'].children.find(node=>node.className==='signal-panel-legend');
  assert.equal(legend.textContent,'观察不可用：观察计算失败：行情缺日');
  assert.equal(svg.children.filter(node=>node.attributes['data-signal-series']==='line').length,8);
  assert.doesNotMatch(svg.textContent,/旧事件说明/,'failure must not introduce stale facts into the event region');
  svg.children.at(-1).listeners.pointermove({clientX:928,clientY:(Number.parseFloat(controls.style.top)+35)*800/Number(svg.attributes.viewBox.split(' ')[3])});
  assert.match(nodes['forward-tooltip'].innerHTML,/观察不可用.*观察计算失败：行情缺日/);
  assert.doesNotMatch(nodes['forward-tooltip'].innerHTML,/10\.00%/);
});
