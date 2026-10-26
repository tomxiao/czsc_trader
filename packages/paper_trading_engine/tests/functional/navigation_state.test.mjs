import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../../src/paper_trading_engine/static/app.js',import.meta.url),'utf8')
  .replace(/^import .*;\r?\n/gm,'').replace(/\bexport /g,'')
  .replace("if(typeof document!=='undefined')boot();",'');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const response=payload=>({ok:true,status:200,json:async()=>payload});
function setup(fetcher){
  const node=()=>({hidden:true,disabled:false,dataset:{},attributes:{},style:{},innerHTML:'existing page',textContent:'',
    setAttribute(key,value){this.attributes[key]=value;},removeAttribute(key){delete this.attributes[key];}});
  const nodes=Object.fromEntries(['app','routeLoading','pollWarning','accountSwitch','retryAccountChart','channelSwitch','systemStatus','closeSystemEvents'].map(key=>[key,node()]));
  const ack=node(),actions=[nodes.accountSwitch,ack,nodes.retryAccountChart,nodes.channelSwitch];
  const updates=[],renders=[];
  const location={pathname:'/accounts/alpha',search:''};
  const listeners={};
  const window={scrollY:450,scrollX:0,innerHeight:900,scrollTo(options){this.scrollY=options.top;},addEventListener(name,callback){listeners[name]=callback;}};
  const history={state:{},replaceState(value,title,url){this.state=value;if(url){const parsed=new URL(url,'http://fixture');location.pathname=parsed.pathname;location.search=parsed.search;}},pushState(value,title,url){this.replaceState(value,title,url);}};
  const document={
    querySelector(selector){return nodes[selector.slice(1)]||null;},
    querySelectorAll(selector){
      if(selector==='[data-navigation-disabled]')return actions.filter(item=>'navigationDisabled' in item.dataset);
      if(selector.includes('#accountSwitch'))return actions;
      return [];
    },
  };
  const storage=new Map();
  const context={AbortController,URLSearchParams,URL,Intl,Date,setTimeout,clearTimeout,setInterval(){},console,document,window,history,location,
    fetch:fetcher,localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    reserveViewport(root,y){root.style.minHeight=`${y+900-76}px`;},
    captureView(){return {};},restoreView(){},
    updateView(root,render,options={}){updates.push(options);render();window.scrollTo({top:options.y??window.scrollY});},
    recordRender(kind,snapshot){renders.push({kind,snapshot});},
  };
  runInNewContext(source+`
    renderAccount=snapshot=>recordRender('account',snapshot);
    renderChannel=snapshot=>recordRender('channel',snapshot);
    renderComparison=snapshot=>recordRender('comparison',snapshot);
    renderAudit=snapshot=>recordRender('audit',snapshot);
    applyAccountChart=()=>{};
    globalThis.subject={state,loadRoute,beginNavigation,finishNavigation,navigate,snapshotFingerprint,
      installListeners(){
        const originalLoad=loadRoute,originalRefresh=refreshSystem;
        loadRoute=()=>{};refreshSystem=()=>{};boot();
        loadRoute=originalLoad;refreshSystem=originalRefresh;
      },
    };
  `,context);
  return {...context,...context.subject,nodes,actions,updates,renders,listeners};
}
const account=id=>({account_id:id,name:id,run_state:'RUNNING'});

test('navigation disables old account mutation controls but preserves already-disabled state',()=>{
  const env=setup();env.state.accounts=[account('alpha')];env.actions[2].disabled=true;
  env.beginNavigation(450);
  assert.equal(env.nodes.routeLoading.hidden,false);
  assert.match(env.nodes.routeLoading.textContent,/alpha/);
  assert.equal(env.nodes.app.attributes['aria-busy'],'true');
  assert.ok(env.actions.every(item=>item.disabled));
  env.finishNavigation();
  assert.equal(env.nodes.routeLoading.hidden,true);
  assert.equal(env.nodes.app.attributes['aria-busy'],undefined);
  assert.equal(env.actions[0].disabled,false);
  assert.equal(env.actions[2].disabled,true);
});

test('empty account index clears navigation loading and allows future polling',async()=>{
  const env=setup(async()=>response({accounts:[]}));
  env.state.renderedScope='alpha';env.beginNavigation(450);
  await env.loadRoute({showLoading:false});
  assert.equal(env.state.navigation,null);
  assert.equal(env.nodes.routeLoading.hidden,true);
  assert.equal(env.nodes.app.attributes['aria-busy'],undefined);
  assert.match(env.nodes.app.innerHTML,/暂无可展示/);
  assert.equal(env.location.pathname,'/accounts/');
});

test('history scroll target applies even when unchanged snapshot needs no rendering',async()=>{
  const snapshot={orders:[],accounts:[]},accounts=[account('alpha')];
  const env=setup(async url=>response(url==='/api/virtual-accounts'?{accounts}:snapshot));
  env.location.pathname='/channels/futu-simulate-cn';
  env.state.renderedScope='channel';
  env.state.fingerprint=env.snapshotFingerprint({accounts,snapshot});
  env.window.scrollY=20;env.beginNavigation(320);
  await env.loadRoute({showLoading:false});
  assert.equal(env.window.scrollY,320);
  assert.equal(env.renders.length,0);
  assert.equal(env.state.navigation,null);
});

test('same-page navigation follows user scrolling while the response is pending',async()=>{
  const index=deferred(),accounts=[account('alpha')],snapshot={orders:[],accounts:[]};
  const env=setup(async url=>url==='/api/virtual-accounts'?index.promise:response(snapshot));
  env.installListeners();env.location.pathname='/channels/futu-simulate-cn';
  env.state.renderedScope='channel';env.state.fingerprint=env.snapshotFingerprint({accounts,snapshot});
  env.beginNavigation(450,true);
  const loading=env.loadRoute({showLoading:false});
  env.window.scrollY=700;env.listeners.scroll();
  index.resolve(response({accounts}));await loading;
  assert.equal(env.window.scrollY,700);
  assert.equal(env.state.navigation,null);
});

test('explicit history target is not overwritten by scroll events while loading',async()=>{
  const index=deferred(),accounts=[account('alpha')],snapshot={orders:[],accounts:[]};
  const env=setup(async url=>url==='/api/virtual-accounts'?index.promise:response(snapshot));
  env.installListeners();env.location.pathname='/channels/futu-simulate-cn';
  env.state.renderedScope='channel';env.state.fingerprint=env.snapshotFingerprint({accounts,snapshot});
  env.beginNavigation(320);
  const loading=env.loadRoute({showLoading:false});
  env.window.scrollY=700;env.listeners.scroll();
  index.resolve(response({accounts}));await loading;
  assert.equal(env.window.scrollY,320);
});

test('late account-index response cannot replace newer scope account facts',async()=>{
  const old=deferred();let indexCalls=0;
  const env=setup(async url=>{
    if(url==='/api/virtual-accounts')return ++indexCalls===1?old.promise:response({accounts:[account('beta')]});
    if(url.endsWith('/chart'))return response({scope:{account_id:'beta'},status:'READY'});
    return response({scope:{account_id:'beta'},account:account('beta')});
  });
  const first=env.loadRoute({showLoading:false});
  env.location.pathname='/accounts/beta';env.beginNavigation(450);
  await env.loadRoute({showLoading:false});
  old.resolve(response({accounts:[account('alpha')]}));await first;
  assert.equal(env.state.accounts[0].account_id,'beta');
  assert.equal(env.state.renderedScope,'beta');
  assert.deepEqual(env.renders.map(item=>item.snapshot.scope.account_id),['beta']);
});

test('late failed request cannot replace newer success with error or loading state',async()=>{
  const old=deferred();let indexCalls=0;
  const env=setup(async url=>{
    if(url==='/api/virtual-accounts')return ++indexCalls===1?old.promise:response({accounts:[account('beta')]});
    if(url.endsWith('/chart'))return response({scope:{account_id:'beta'},status:'READY'});
    return response({scope:{account_id:'beta'},account:account('beta')});
  });
  const first=env.loadRoute({showLoading:false});
  env.location.pathname='/accounts/beta';env.beginNavigation(450);
  await env.loadRoute({showLoading:false});
  old.reject(new Error('obsolete connection failure'));await first;
  assert.equal(env.state.renderedScope,'beta');
  assert.equal(env.nodes.pollWarning.hidden,true);
  assert.equal(env.nodes.routeLoading.hidden,true);
  assert.doesNotMatch(env.nodes.app.innerHTML,/obsolete connection failure/);
});
