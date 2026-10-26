// UI state only: no account, order or strategy facts are cached here.
function elementKey(element, root) {
  if (!element || element === root) return '';
  if (element.id) return `#${CSS.escape(element.id)}`;
  for (const attribute of ['data-event-id','data-account','data-account-section','data-account-tab','data-record-tab','data-page-direction','name']) {
    if (element.hasAttribute(attribute)) return `${elementKey(element.parentElement,root)} > ${element.tagName.toLowerCase()}[${attribute}="${CSS.escape(element.getAttribute(attribute))}"]`;
  }
  const index=[...element.parentElement.children].indexOf(element)+1;
  return `${elementKey(element.parentElement,root)} > ${element.tagName.toLowerCase()}:nth-child(${index})`;
}
function locate(root,key){return key?root.querySelector(key.startsWith(' > ')?`:scope${key}`:key):null;}

export function captureView(root) {
  const active=root.contains(document.activeElement)?document.activeElement:null;
  const boundary=document.querySelector('.system-bar')?.getBoundingClientRect().bottom??0;
  const anchor=[...root.querySelectorAll('[data-event-id]')].find(element=>{
    const rect=element.getBoundingClientRect();return rect.bottom>boundary&&rect.top<window.innerHeight;
  });
  return {
    anchor:anchor?{key:elementKey(anchor,root),top:anchor.getBoundingClientRect().top}:null,
    focus:active?elementKey(active,root):null,
    selection:active&&typeof active.selectionStart==='number'?[active.selectionStart,active.selectionEnd]:null,
    elements:[...root.querySelectorAll('details,input,select,textarea,.table-wrap,.sidebar')].map(element=>({
      key:elementKey(element,root), open:element.tagName==='DETAILS'?element.open:undefined,
      value:element.matches('input:not([type=checkbox]):not([type=radio]),select,textarea')?element.value:undefined,
      left:element.scrollLeft, top:element.scrollTop,
    })),
  };
}

export function restoreView(root, saved) {
  for(const item of saved.elements){
    const element=locate(root,item.key);if(!element)continue;
    if(item.open!==undefined)element.open=item.open;
    if(item.value!==undefined)element.value=item.value;
    element.scrollLeft=item.left;element.scrollTop=item.top;
  }
  const active=locate(root,saved.focus);
  if(active&&!active.disabled){active.focus({preventScroll:true});if(saved.selection)active.setSelectionRange(...saved.selection);}
}

// Keep enough document height to avoid the browser clamping scrollY during a
// synchronous DOM replacement, including transitions to a shorter page.
export function reserveViewport(root,y=window.scrollY){
  const top=root.getBoundingClientRect().top+window.scrollY;
  root.style.minHeight=`${Math.max(0,y+window.innerHeight-top)}px`;
}

export function updateView(root,render,{preserve=true,y=window.scrollY}={}){
  const saved=preserve?captureView(root):null;
  reserveViewport(root,y);
  render();
  if(saved)restoreView(root,saved);
  const anchor=saved?.anchor&&locate(root,saved.anchor.key);
  if(anchor){y=window.scrollY+anchor.getBoundingClientRect().top-saved.anchor.top;reserveViewport(root,y);}
  window.scrollTo({left:window.scrollX,top:y,behavior:'instant'});
}
