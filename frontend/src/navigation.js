const $ = id => document.getElementById(id);
let section = 'workspace';
let canManage = false;
export function showArea(area, focus = false) {
  if (!['library', 'chat', 'evidence'].includes(area)) return;
  $('knowledge-workspace').dataset.activeArea = area;
  for (const button of document.querySelectorAll('[data-area]')) button.setAttribute('aria-pressed', String(button.dataset.area === area));
  if (area === 'evidence') $('grounds-indicator').hidden = true;
  if (focus && matchMedia('(max-width:1179px)').matches) {
    const target = $(area); target.tabIndex = -1; target.focus({preventScroll:true});
  }
}
export function showSection(value) {
  section = value === 'administration' && canManage ? 'administration' : 'workspace';
  $('knowledge-workspace').hidden = section !== 'workspace';
  document.querySelector('.area-switcher').hidden = section !== 'workspace';
  $('administration').hidden = section !== 'administration';
  for (const name of ['workspace', 'administration']) {
    const button = $(`nav-${name}`);
    if (section === name) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  }
}
export function configureNavigation(role) {
  canManage = role !== 'user';
  $('nav-administration').hidden = !canManage;
  showSection(section);
}
export function resetNavigation() {section = 'workspace'; showArea('chat');}
$('nav-workspace').onclick = () => showSection('workspace');
$('nav-administration').onclick = () => showSection('administration');
for (const button of document.querySelectorAll('[data-area]')) button.onclick = () => showArea(button.dataset.area, true);
