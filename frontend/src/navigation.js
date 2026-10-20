import {token} from './auth.js';

const $ = id => document.getElementById(id);
const narrowWorkspace=matchMedia('(max-width:1179px)');
const mobileMenu=matchMedia('(max-width:959px)');
let section = sessionStorage.getItem('rag:section') || 'workspace';
let canManage = false;
const areaFocus = new Map();
let historySizeFrame;
function sizeHistory() {
  cancelAnimationFrame(historySizeFrame);
  historySizeFrame=requestAnimationFrame(()=>{
    const main=document.querySelector('main');
    main.style.removeProperty('--history-extra-height');
    const history=$('history');
    if($('workspace').hidden||$('knowledge-workspace').hidden||!history.getClientRects().length)return;
    // Measure the original layout, then add nine original history heights.
    const extra=history.getBoundingClientRect().height*9+Math.max(0,main.scrollHeight-main.clientHeight);
    main.style.setProperty('--history-extra-height',`${extra}px`);
    if(history.querySelector('article')) {
      history.scrollTop=history.scrollHeight;
      if($('knowledge-workspace').dataset.activeArea==='chat')$('question-form').scrollIntoView({block:'end'});
    }
  });
}
window.addEventListener('resize',sizeHistory);
document.addEventListener('rag:section-changed',sizeHistory);
document.addEventListener('rag:history-changed',sizeHistory);
function compactChat() {
  $('source-selection').open=false;
}
function sidebar(open,focus=false) {
  open=Boolean(open&&mobileMenu.matches);
  $('workspace').dataset.menuOpen=String(open);
  $('sidebar-toggle').setAttribute('aria-expanded',String(open));
  $('sidebar-backdrop').hidden=!open;
  $('workspace-content').inert=open;
  document.querySelector('.app-header').inert=open;
  document.querySelector('.mobile-workspace-bar').inert=open;
  if(open) {
    $('workspace-sidebar').setAttribute('role','dialog');
    $('workspace-sidebar').setAttribute('aria-modal','true');
    $('close-sidebar').focus();
  } else {
    $('workspace-sidebar').removeAttribute('role');
    $('workspace-sidebar').removeAttribute('aria-modal');
    if(focus&&mobileMenu.matches)$('sidebar-toggle').focus();
  }
}
$('sidebar-toggle').onclick=()=>sidebar(true);
$('close-sidebar').onclick=()=>sidebar(false,true);
$('sidebar-backdrop').onclick=()=>sidebar(false,true);
mobileMenu.addEventListener('change',()=>sidebar(false));
$('workspace-sidebar').addEventListener('keydown',event=>{
  if($('workspace').dataset.menuOpen!=='true')return;
  if(event.key==='Escape'){event.preventDefault();sidebar(false,true);}
  if(event.key==='Tab') {
    const items=Array.from($('workspace-sidebar').querySelectorAll('button,summary')).filter(item=>item.getClientRects().length&&!item.disabled);
    const first=items[0],last=items.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
});
document.addEventListener('focusin',event=>{
  const area = event.target.closest?.('.work-area');
  if(area) areaFocus.set(area.id,event.target);
});
function markArea(area) {
  for(const button of document.querySelectorAll('[data-area]'))button.setAttribute('aria-pressed',String(button.dataset.area===area));
}
export function showArea(area, focus = false) {
  if(!['library','chat','evidence'].includes(area))return;
  if(area==='library') {showSection('library');return;}
  showSection('workspace');
  $('knowledge-workspace').dataset.activeArea=area;
  if(area==='evidence') {
    $('knowledge-workspace').dataset.evidenceOpen='true';$('evidence').hidden=false;
    $('grounds-indicator').hidden=true;$('open-evidence').setAttribute('aria-expanded','true');
  }
  markArea(area);
  if(focus) {
    const remembered=areaFocus.get(area),target=remembered?.isConnected?remembered:$(area);
    target.tabIndex=target.tabIndex<0?-1:target.tabIndex;target.focus({preventScroll:true});
  }
}
export function showSection(value) {
  sidebar(false);
  section=value==='administration'&&!canManage?'workspace':value;
  if(!['workspace','library','administration'].includes(section))section='workspace';
  if(token())sessionStorage.setItem('rag:section',section);else sessionStorage.removeItem('rag:section');
  $('knowledge-workspace').hidden=section!=='workspace';$('library').hidden=section!=='library';$('administration').hidden=section!=='administration';
  for(const name of ['workspace','library','administration']) {
    const button=$(`nav-${name}`);
    if(section===name)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  }
  if(section==='library')markArea('library');
  $('mobile-section-title').textContent={workspace:'Беседы',library:'Документы',administration:'Управление'}[section];
  document.dispatchEvent(new CustomEvent('rag:section-changed',{detail:section}));
}
export function configureNavigation(role) {canManage=role!=='user';$('nav-administration').hidden=!canManage;showSection(section);compactChat();}
function closeEvidence(focus=false) {
  $('knowledge-workspace').dataset.evidenceOpen='false';$('knowledge-workspace').dataset.activeArea='chat';
  $('evidence').hidden=true;$('open-evidence').setAttribute('aria-expanded','false');markArea('chat');
  if(focus)$('open-evidence').focus({preventScroll:true});
  sizeHistory();
}
export function resetNavigation() {section='workspace';areaFocus.clear();closeEvidence();showSection(section);}
$('nav-workspace').onclick=()=>showArea('chat');
$('nav-library').onclick=()=>showArea('library');
$('nav-administration').onclick=()=>showSection('administration');
$('open-evidence').onclick=()=>showArea('evidence',true);
$('close-evidence').onclick=()=>closeEvidence(true);
$('question').addEventListener('focus',compactChat);
narrowWorkspace.addEventListener('change',()=>{if(document.activeElement===$('question'))compactChat();});
document.querySelector('.skip-link').onclick=event=>{
  event.preventDefault();
  if(!$('workspace').hidden){showArea('chat');$('question').focus();}
  else if(!$('authentication').inert)document.querySelector('#authentication form:not([hidden]) input')?.focus();
  else {$('status').tabIndex=-1;$('status').focus();}
};
document.addEventListener('rag:show-area',event=>showArea(event.detail,true));
document.querySelector('.brand').onclick=event=>{
  if(!$('workspace').hidden){event.preventDefault();showArea('chat');}
};
