const $ = id => document.getElementById(id);
let section = 'workspace';
let canManage = false;
const areaFocus = new Map();
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
  section=value==='administration'&&!canManage?'workspace':value;
  if(!['workspace','library','administration'].includes(section))section='workspace';
  $('knowledge-workspace').hidden=section!=='workspace';$('library').hidden=section!=='library';$('administration').hidden=section!=='administration';
  for(const name of ['workspace','library','administration']) {
    const button=$(`nav-${name}`);
    if(section===name)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  }
  if(section==='library')markArea('library');
}
export function configureNavigation(role) {canManage=role!=='user';$('nav-administration').hidden=!canManage;showSection(section);}
function closeEvidence(focus=false) {
  $('knowledge-workspace').dataset.evidenceOpen='false';$('knowledge-workspace').dataset.activeArea='chat';
  $('evidence').hidden=true;$('open-evidence').setAttribute('aria-expanded','false');markArea('chat');
  if(focus)$('open-evidence').focus({preventScroll:true});
}
export function resetNavigation() {section='workspace';areaFocus.clear();closeEvidence();showSection(section);}
$('nav-workspace').onclick=()=>showArea('chat');
$('nav-library').onclick=()=>showArea('library');
$('nav-administration').onclick=()=>showSection('administration');
$('open-evidence').onclick=()=>showArea('evidence',true);
$('close-evidence').onclick=()=>closeEvidence(true);
document.addEventListener('rag:show-area',event=>showArea(event.detail,true));
document.querySelector('.brand').onclick=event=>{
  if(!$('workspace').hidden){event.preventDefault();showArea('chat');}
};
