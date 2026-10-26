import assert from 'node:assert/strict';
import test from 'node:test';
import {captureView,restoreView,reserveViewport,updateView} from '../../src/paper_trading_engine/static/view_state.js';

// Small DOM fixture for identity/state tests. Real browser checks cover layout.
class Element {
  constructor(tag,attributes={},children=[]){
    this.tagName=tag.toUpperCase();this.attributes=attributes;this.children=[];
    this.id=attributes.id||'';this.style={};this.scrollLeft=0;this.scrollTop=0;
    this.open=false;this.value='';this.disabled=false;this.checked=false;
    this.replaceChildren(...children);
  }
  replaceChildren(...children){for(const old of this.children)old.parentElement=null;this.children=children;for(const child of children)child.parentElement=this;}
  hasAttribute(key){return key in this.attributes;}
  getAttribute(key){return this.attributes[key];}
  contains(element){return element===this||this.children.some(child=>child.contains(element));}
  descendants(){return this.children.flatMap(child=>[child,...child.descendants()]);}
  matches(selector){
    return selector.split(',').some(part=>{
      if(part.startsWith('input:not'))return this.tagName==='INPUT'&&!['checkbox','radio'].includes(this.attributes.type);
      if(part.startsWith('['))return this.hasAttribute(part.slice(1,-1));
      if(part.startsWith('.'))return (this.attributes.class||'').split(' ').includes(part.slice(1));
      return this.tagName===part.toUpperCase();
    });
  }
  querySelectorAll(selector){return this.descendants().filter(element=>element.matches(selector));}
  querySelector(selector){
    const parts=selector.split(' > ');
    let candidates=parts[0]===':scope'?[this]:this.descendants().filter(element=>element.id===parts[0].slice(1));
    for(const part of parts.slice(1)){
      candidates=candidates.flatMap(element=>element.children).filter(element=>{
        const attr=part.match(/^([a-z]+)\[([^=]+)="([^"]*)"\]$/);
        if(attr)return element.tagName===attr[1].toUpperCase()&&element.getAttribute(attr[2])===attr[3];
        const nth=part.match(/^([a-z]+):nth-child\((\d+)\)$/);
        return nth&&element.tagName===nth[1].toUpperCase()&&element.parentElement.children.indexOf(element)+1===Number(nth[2]);
      });
    }
    return candidates[0]||null;
  }
  focus(options){this.focusOptions=options;document.activeElement=this;}
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
  getBoundingClientRect(){const top=(this.documentTop??76)-window.scrollY;return {top,bottom:top+(this.height??0)};}
}
function environment(t,children=[]){
  const previous={window:globalThis.window,document:globalThis.document,CSS:globalThis.CSS};
  const calls=[];
  globalThis.window={scrollY:450,scrollX:12,innerHeight:900,scrollTo(options){calls.push(options);this.scrollY=options.top;}};
  globalThis.document={activeElement:null,querySelector:selector=>selector==='.system-bar'?{getBoundingClientRect:()=>({bottom:76})}:null};
  globalThis.CSS={escape:value=>value};
  t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}});
  return {root:new Element('main',{id:'app'},children),calls};
}

test('replacement reserves document height before rendering and restores viewport in same update',t=>{
  const {root,calls}=environment(t);
  updateView(root,()=>{assert.equal(root.style.minHeight,'1274px');window.scrollY=0;});
  assert.deepEqual(calls,[{left:12,top:450,behavior:'instant'}]);
  assert.equal(window.scrollY,450);
});

test('explicit top navigation releases old height and accepts zero as a target',t=>{
  const {root,calls}=environment(t);
  root.style.minHeight='2000px';
  updateView(root,()=>{}, {preserve:false,y:0});
  assert.equal(root.style.minHeight,'824px');
  assert.equal(calls[0].top,0);
  reserveViewport(root,-2000);
  assert.equal(root.style.minHeight,'0px');
});

test('poll replacement keeps a draft, selection and focus without scrolling',t=>{
  const input=new Element('input',{name:'account_id'});
  const form=new Element('form',{id:'auditFilters'},[input]);
  const {root}=environment(t,[form]);
  input.value='unfinished draft';input.setSelectionRange(2,7);document.activeElement=input;
  const replacement=new Element('input',{name:'account_id'});
  replacement.value='server filter';
  updateView(root,()=>root.replaceChildren(new Element('form',{id:'auditFilters'},[replacement])));
  assert.equal(replacement.value,'unfinished draft');
  assert.equal(document.activeElement,replacement);
  assert.deepEqual(replacement.focusOptions,{preventScroll:true});
  assert.deepEqual([replacement.selectionStart,replacement.selectionEnd],[2,7]);
});

test('event details retain state by event identity when a new event is inserted',t=>{
  const details=new Element('details');details.open=true;
  const {root}=environment(t,[new Element('article',{'data-event-id':'old-event'},[details])]);
  const fresh=new Element('details'),old=new Element('details');
  updateView(root,()=>root.replaceChildren(
    new Element('article',{'data-event-id':'new-event'},[fresh]),
    new Element('article',{'data-event-id':'old-event'},[old]),
  ));
  assert.equal(old.open,true);assert.equal(fresh.open,false);
});

test('new events above the viewport preserve the visible event reading position',t=>{
  const above=new Element('article',{'data-event-id':'above'});above.documentTop=300;above.height=100;
  const visible=new Element('article',{'data-event-id':'reading'});visible.documentTop=550;visible.height=160;
  const {root}=environment(t,[above,visible]);
  const nextAbove=new Element('article',{'data-event-id':'above'});nextAbove.documentTop=480;nextAbove.height=100;
  const nextVisible=new Element('article',{'data-event-id':'reading'});nextVisible.documentTop=730;nextVisible.height=160;
  const inserted=new Element('article',{'data-event-id':'new'});inserted.documentTop=300;inserted.height=180;
  updateView(root,()=>root.replaceChildren(inserted,nextAbove,nextVisible));
  assert.equal(window.scrollY,630);
  assert.equal(nextVisible.getBoundingClientRect().top,100);
});

test('removing the visible event keeps the current offset without using a different event anchor',t=>{
  const visible=new Element('article',{'data-event-id':'expired'});visible.documentTop=550;visible.height=160;
  const {root}=environment(t,[visible]);
  const next=new Element('article',{'data-event-id':'different'});next.documentTop=730;next.height=160;
  updateView(root,()=>root.replaceChildren(next));
  assert.equal(window.scrollY,450);
});

test('events below the viewport are not reading anchors while the user reads filters',t=>{
  const below=new Element('article',{'data-event-id':'below'});below.documentTop=1400;below.height=160;
  const {root}=environment(t,[below]);
  const inserted=new Element('article',{'data-event-id':'new'});inserted.documentTop=1400;inserted.height=180;
  const nextBelow=new Element('article',{'data-event-id':'below'});nextBelow.documentTop=1580;nextBelow.height=160;
  updateView(root,()=>root.replaceChildren(inserted,nextBelow));
  assert.equal(window.scrollY,450);
});

test('table horizontal scroll and sidebar vertical scroll survive section replacement',t=>{
  const table=new Element('div',{class:'table-wrap'}),sidebar=new Element('aside',{class:'sidebar','data-account-section':'sidebar'});
  table.scrollLeft=310;sidebar.scrollTop=95;
  const {root}=environment(t,[sidebar,new Element('section',{'data-account-section':'orders'},[table])]);
  const nextTable=new Element('div',{class:'table-wrap'}),nextSidebar=new Element('aside',{class:'sidebar','data-account-section':'sidebar'});
  updateView(root,()=>root.replaceChildren(nextSidebar,new Element('section',{'data-account-section':'orders'},[nextTable])));
  assert.equal(nextTable.scrollLeft,310);assert.equal(nextSidebar.scrollTop,95);
});

test('cross-scope updates do not restore old form or expansion state',t=>{
  const old=new Element('details',{id:'details'});old.open=true;
  const {root}=environment(t,[old]);
  const fresh=new Element('details',{id:'details'});
  updateView(root,()=>root.replaceChildren(fresh),{preserve:false});
  assert.equal(fresh.open,false);
});

test('pagination focus follows next direction after target page numbers change',t=>{
  const previous=new Element('button',{'data-page-direction':'previous','data-record-page':'1'});
  const next=new Element('button',{'data-page-direction':'next','data-record-page':'3'});
  const {root}=environment(t,[new Element('section',{id:'record-panel-orders'},[previous,next])]);
  document.activeElement=next;
  const freshPrevious=new Element('button',{'data-page-direction':'previous','data-record-page':'2'});
  const freshNext=new Element('button',{'data-page-direction':'next','data-record-page':'4'});
  updateView(root,()=>root.replaceChildren(new Element('section',{id:'record-panel-orders'},[freshPrevious,freshNext])));
  assert.equal(document.activeElement,freshNext);
  assert.deepEqual(freshNext.focusOptions,{preventScroll:true});
  assert.equal(freshPrevious.focusOptions,undefined);
});

test('removed or newly disabled focus targets are not focused and checkboxes stay server-owned',t=>{
  const button=new Element('button',{id:'action'}),checkbox=new Element('input',{id:'selected',type:'checkbox'});
  checkbox.checked=true;
  const {root}=environment(t,[button,checkbox]);document.activeElement=button;
  const saved=captureView(root);
  root.replaceChildren();assert.doesNotThrow(()=>restoreView(root,saved));
  const disabled=new Element('button',{id:'action'});disabled.disabled=true;
  const freshCheckbox=new Element('input',{id:'selected',type:'checkbox'});
  root.replaceChildren(disabled,freshCheckbox);restoreView(root,saved);
  assert.equal(disabled.focusOptions,undefined);assert.equal(freshCheckbox.checked,false);
});
