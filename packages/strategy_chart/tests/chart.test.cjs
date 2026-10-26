'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
// Small DOM adapter exercises the public mount API without a browser dependency.
// Pixel layout is additionally checked in the real browser.
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.attrs={};this.dataset={};this.style={};this.listeners={};this.hidden=false;this.clientWidth=1440;this.offsetWidth=200;this.offsetHeight=100;this._text='';this.className='';this.classList={add:(...names)=>this.className+=' '+names.join(' ')};}
 set textContent(value){this._text=String(value);this.children=[];}
 get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
 setAttribute(key,value){this.attrs[key]=String(value);}
 appendChild(child){child.parent=this;this.children.push(child);return child;}
 append(...children){children.forEach(child=>this.appendChild(child));}
 replaceChildren(...children){this.children.forEach(x=>x.parent=null);this.children=[];this._text='';this.append(...children);}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null;}
 get options(){return this.children;}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 querySelectorAll(selector){const match=node=>selector[0]==='#'?node.attrs.id===selector.slice(1):selector[0]==='.'?node.className.split(/\s+/).includes(selector.slice(1)):selector.startsWith('[data-')?Object.hasOwn(node.dataset,selector.slice(6,-1)):node.tagName===selector;const result=[];const walk=node=>node.children.forEach(child=>{if(match(child))result.push(child);walk(child);});walk(this);return result;}
 addEventListener(type,handler,options={}){(this.listeners[type]??=[]).push(handler);options.signal?.addEventListener('abort',()=>this.listeners[type]=this.listeners[type].filter(x=>x!==handler),{once:true});}
 fire(type,options={}){const event={clientX:70,clientY:50,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...options};for(const handler of this.listeners[type]||[])handler(event);return event;}
 focus(){this.focused=true;}
 getContext(){return {font:'',measureText:text=>({width:String(text).length*6})};}
 getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:700};}
}
function fixture(){
 const root=new Element();
 const make=(tag,id,parent=root)=>{const el=new Element(tag);if(id)el.setAttribute('id',id);parent.append(el);return el;};
 const stage=make('section','forward-stage'),svg=make('svg','forward-svg',stage);svg.setAttribute('tabindex','0');make('div','forward-tooltip',stage);
 for(const range of ['20','40','all']){const button=make('button');button.dataset.range=range;}
 for(const layer of ['signal','fill','position']){const button=make('button');button.dataset.layer=layer;}
 const window=new Element();window.parent=window;window.innerHeight=960;
 const document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
 const observers=[];
 class ResizeObserver{constructor(callback){this.callback=callback;this.disconnected=false;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}}
 const scope={window,document,HTMLElement:Element,AbortController,ResizeObserver,Intl,console,getComputedStyle:()=>({getPropertyValue:()=> '#fff',fontFamily:'sans-serif'})};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/strategy_chart/static/strategy-chart.js'),'utf8'),scope);
 return {root,stage,svg,window,observers,mount:scope.window.mountStrategyChart};
}
function context(){
 const narrative={state_key:'state',case_key:'wait',judgment:'等待条件满足',basis:[{key:'one',text:'<img src=x onerror=alert(1)>'}],next_watch:'等待下一次信号',explanation:'解释文本'};
 const panel={groups:[],series:[],states:[{key:'state',label:'状态',description:'',options:[{key:'wait',label:'等待'}],value:'wait',status:'AVAILABLE',reason:null}],explanation:narrative};
 return {mode:'BACKTEST',strategy:{reference_id:'TEST',symbol:'TEST'},window:{start:'2026-01-05',end:'2026-01-07'},market_data:{as_of:'2026-01-07',bars:['2026-01-05','2026-01-06','2026-01-07'].map(date=>({date,open:1,high:1.1,low:.9,close:1}))},observations:[{signal_date:'2026-01-05',decision_id:'old',observation:{status:'READY',definition_sha256:'old',series:[],facts:[]}},{signal_date:'2026-01-06',decision_id:'failed',observation:{status:'UNAVAILABLE',message:'计算错误'}},{signal_date:'2026-01-07',decision_id:'current',observation:{status:'READY',definition_sha256:'current',series:[],facts:[],signal_panel:panel}}],execution:{decisions:[],fills:[{fill_id:'trade',session:'2026-01-10',occurred_at:'2026-01-10',time_precision:'SESSION',side:'BUY',quantity:100,price:1,fee:.1}],snapshots:[{session:'2026-01-07',quantity:100}]}};
}
test('snapshot interpretation is text only and explanation preserves judgment',()=>{
 const f=fixture();f.mount(f.root,context());const reading=f.root.querySelector('.signal-reading');
 assert.match(reading.textContent,/等待条件满足/);assert.match(reading.textContent,/<img src=x/);assert.equal(reading.querySelector('img'),null);
 reading.querySelector('button').fire('click');assert.match(reading.textContent,/当前判断等待条件满足/);assert.match(reading.textContent,/怎么看这个判断解释文本/);assert.match(reading.textContent,/接下来关注等待下一次信号/);
});
test('chart keyboard selection clears prior judgment and preserves non-trading event precision and fee',()=>{
 const f=fixture();f.mount(f.root,context());assert.equal(f.root.querySelector('#forward-event-date'),null);f.svg.fire('keydown',{key:'End'});
 assert.match(f.root.querySelector('.signal-reading').textContent,/当日没有信号观察/);assert.doesNotMatch(f.root.querySelector('.signal-reading').textContent,/等待条件满足/);
 const svg=f.root.querySelector('#forward-svg').textContent;assert.match(svg,/非交易日/);assert.match(svg,/未记录时刻/);assert.match(svg,/费用 0.10 元/);assert.doesNotMatch(svg,/08:00:00/);
});
test('unavailable and legacy observations remain explicit',()=>{
 const f=fixture();f.mount(f.root,context());f.svg.fire('keydown',{key:'ArrowLeft'});assert.match(f.root.querySelector('.signal-reading').textContent,/观察不可用.*计算错误/);
 f.svg.fire('keydown',{key:'Home'});assert.equal(f.root.querySelector('.signal-reading').hidden,true);assert.equal(f.root.querySelector('.signal-legacy-notice').hidden,false);assert.match(f.root.querySelector('.signal-legacy-notice').textContent,/该记录未提供解释/);
});

test('chart keyboard navigation includes non-trading dates and stops at both boundaries',()=>{
 const f=fixture();f.mount(f.root,context());assert.equal(f.svg.attrs.tabindex,'0');
 assert.equal(f.svg.fire('keydown',{key:'Home'}).defaultPrevented,true);const first=f.svg.textContent;
 assert.equal(f.svg.fire('keydown',{key:'ArrowLeft'}).defaultPrevented,true);assert.equal(f.svg.textContent,first);
 f.svg.fire('keydown',{key:'ArrowRight'});assert.match(f.root.querySelector('.signal-reading').textContent,/观察不可用.*计算错误/);
 f.svg.fire('keydown',{key:'ArrowRight'});assert.match(f.root.querySelector('.signal-reading').textContent,/等待条件满足/);
 f.svg.fire('keydown',{key:'ArrowRight'});assert.match(f.svg.textContent,/2026-01-10.*非交易日/);const last=f.svg.textContent;
 assert.equal(f.svg.fire('keydown',{key:'ArrowRight'}).defaultPrevented,true);assert.equal(f.svg.textContent,last);
 assert.equal(f.svg.fire('keydown',{key:'Enter'}).defaultPrevented,false);assert.equal(f.svg.textContent,last);
 f.svg.fire('keydown',{key:'Home'});f.svg.fire('keydown',{key:'End'});assert.equal(f.svg.textContent,last);
});

test('clicking the chart selects a date and focuses keyboard navigation',()=>{
 const f=fixture();f.mount(f.root,context());f.svg.children.at(-1).fire('click');
 assert.equal(f.svg.focused,true);assert.equal(f.root.querySelector('#forward-tooltip').hidden,true);
 assert.equal(f.root.querySelector('.signal-legacy-notice').hidden,false);
 f.svg.fire('keydown',{key:'ArrowRight'});assert.match(f.root.querySelector('.signal-reading').textContent,/观察不可用.*计算错误/);
});
test('mounts are isolated and destroy releases listeners and observer before remount',()=>{
 const f=fixture(),other=fixture();const view=f.mount(f.root,context());other.mount(other.root,context());
 f.svg.fire('keydown',{key:'ArrowLeft'});assert.match(other.root.querySelector('.signal-reading').textContent,/等待条件满足/);
 assert.throws(()=>f.mount(f.root,context()),/already mounted/);view.destroy();view.destroy();assert.equal(f.observers[0].disconnected,true);assert.equal(f.svg.listeners.keydown.length,0);assert.equal(f.window.listeners.resize.length,0);assert.equal(f.root.querySelector('.signal-reading'),null);
 f.mount(f.root,context());assert.equal(f.svg.listeners.keydown.length,1);assert.equal(f.root.querySelectorAll('.signal-reading').length,1);
});
test('event facts remain accessible with no market bars',()=>{
 const f=fixture(),data=context();data.market_data.bars=[];f.mount(f.root,data);const svg=f.root.querySelector('#forward-svg').textContent;assert.match(svg,/没有可展示的行情/);assert.match(svg,/2026-01-10/);assert.match(svg,/买入 100 股/);assert.match(svg,/费用 0.10 元/);
});
test('invalid context and missing shell fail explicitly',()=>{
 const f=fixture(),data=context();delete data.execution.decisions;assert.throws(()=>f.mount(f.root,data),/typed chart context/);
 assert.throws(()=>f.mount(new Element(),context()),/shared chart shell/);assert.equal(f.root.dataset.strategyChartMounted,undefined);
});
