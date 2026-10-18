import { api, publicSettings } from './api.js';
import {Documents} from './documents.js';
import {createAdministration} from './administration.js';
import { token, signIn, signOut } from './auth.js';
import {Conversations} from './conversations.js';
import {messages, status, feedback, roleLabels} from './ui.js';
import {configureNavigation, showArea, resetNavigation} from './navigation.js';

const $ = id => document.getElementById(id);
let conversations;
let workspaceRead=0;
let inputPolicy;
const documents = new Documents({perform, onSources:files=>conversations?.sources(files), inputPolicy:()=>inputPolicy, reveal:()=>showArea('library')});
const administration = createAdministration({perform,openLibrary:(id,email)=>documents.load(id,email)});
async function perform(operation, control) {
  if (control?.disabled) return;
  const focused = document.activeElement === control;
  if (control) {control.disabled = true; control.setAttribute('aria-busy','true'); feedback(control, 'Выполняется…');}
  try { await operation();
    const output = control?.closest('form, li, article, section')?.querySelector(':scope > .operation-status');
    if (control?.isConnected && output?.textContent === 'Выполняется…') feedback(control, 'Готово.');
  }
  catch (error) {
    if (error.message === 'session_changed') return;
    const message = messages[error.message] || 'Не удалось выполнить действие. Проверьте соединение и повторите.';
    status(message, true); feedback(control, message, true);
    // SMTP failure follows committed registration, which already consumed the invite.
    if (error.message === 'mail_delivery_failed') $('register').elements.invitation.value = '';
    if (error.message === 'unauthenticated' || error.message === 'access_denied') {
      signOut();
      showAuthentication();
    }
  } finally { if (control) {control.disabled = false; control.removeAttribute('aria-busy');
    if (focused && control.isConnected && document.activeElement === document.body && !document.querySelector('dialog[open]')) control.focus({preventScroll:true});
  } }
}

function showAuthentication() {
  ++workspaceRead;
  $('document-report').close();
  $('document-report').replaceChildren();
  conversations?.close(); conversations = undefined;
  $('authentication').hidden = false;
  $('workspace').hidden = true;
  $('identity').textContent = '';
  $('session-controls').hidden = true; resetNavigation();
  $('document-editor').close();
  $('confirm-action').close('cancel');
  $('history').replaceChildren();
  $('conversations').replaceChildren();
  administration.clear();
  $('generation-settings').hidden = true;
  documents.clear();
  $('documents').replaceChildren();
  $('document-upload').reset();
}

async function showWorkspace() {
  const reading=++workspaceRead;
  const current = await api('/accounts/me');
  if(reading!==workspaceRead)return;
  $('authentication').hidden = true;
  $('workspace').hidden = false;
  $('session-controls').hidden = false;
  configureNavigation(current.account.role);
  $('identity').textContent = `${current.account.email} · ${roleLabels[current.account.role] || current.account.role}`;
  if (!conversations) conversations = new Conversations(current.account.id, error => perform(() => {throw error;}));
  await conversations.initialize(current.conversations);
  if(reading!==workspaceRead)return;
  if (current.account.role !== 'user') await perform(() => administration.accounts(current.account.role));
  $('generation-settings').hidden = current.account.role !== 'super_admin';
  if (current.account.role === 'super_admin') await perform(()=>administration.settings());
  if(reading!==workspaceRead)return;
  await perform(()=>documents.load(null,'',false), $('refresh-documents'));
}

for (const name of ['register', 'login']) {
  $(name).addEventListener('submit', event => {
    event.preventDefault();
    const form = event.currentTarget;
    perform(async () => {
      const body = Object.fromEntries(new FormData(form));
      if (!body.invitation) delete body.invitation;
      const result = await api(`/accounts/${name}`, 'POST', body);
      form.elements.password.value = '';
      if (name === 'register') {
        form.elements.invitation.value = '';
        status('Откройте письмо и подтвердите email, затем войдите.');
      } else {
        signIn(result.token);
        status('Вы вошли.');
        await showWorkspace();
      }
    }, form.querySelector('button'));
  });
}

$('logout').addEventListener('click', () => perform(async () => {
  try { await api('/accounts/logout', 'POST'); }
  finally { signOut(); showAuthentication(); }
  status('Вы вышли.');
}, $('logout')));

const fragment = new URLSearchParams(location.hash.slice(1));
history.replaceState(null, '', location.pathname + location.search);
let verificationAttempted = false;
function showAuthForm(name) {
  for (const value of ['login','register']) {$(value).hidden = value !== name; $(`show-${value}`).setAttribute('aria-pressed',String(value === name));}
}
$('show-login').onclick = () => showAuthForm('login');
$('show-register').onclick = () => showAuthForm('register');
async function initialize() {
  const {inputs, document_formats: formats} = await publicSettings();
  for (const key of ['email_min', 'email_max', 'password_min', 'password_max', 'token_max', 'filename_max']) {
    if (!Number.isSafeInteger(inputs[key]) || inputs[key] <= 0) throw new Error('invalid_public_settings');
  }
  if (inputs.email_min > inputs.email_max || inputs.password_min > inputs.password_max ||
      !Array.isArray(formats) || !formats.length || formats.some(format => !/^[a-z0-9]+$/.test(format))) {
    throw new Error('invalid_public_settings');
  }
  for (const name of ['login', 'register']) {
    const form = $(name);
    form.elements.email.minLength = inputs.email_min;
    form.elements.email.maxLength = inputs.email_max;
    form.elements.password.minLength = inputs.password_min;
    form.elements.password.maxLength = inputs.password_max;
  }
  $('register').elements.invitation.maxLength = inputs.token_max;
  inputPolicy = inputs;
  $('registration-password-label').textContent = `Пароль (от ${inputs.password_min} символов)`;
  $('document-upload').elements.files.accept = formats.map(format => `.${format}`).join(',');
  $('authentication').inert = false;
  $('authentication').querySelectorAll('button').forEach(button => {button.disabled = false;});
  if (fragment.has('invite')) { $('register').elements.invitation.value = fragment.get('invite'); showAuthForm('register'); }
  if (fragment.has('verify') && !verificationAttempted) { verificationAttempted = true; await perform(async () => {
    await api('/accounts/verify', 'POST', { token: fragment.get('verify') });
    status('Email подтверждён. Теперь войдите.');
  }); }
  if (token()) await perform(showWorkspace);
  document.documentElement.dataset.ready = 'true';
}

async function bootstrap() {
  $('retry-bootstrap').hidden = true;
  try { await initialize(); }
  catch { status('Настройки сервиса недоступны. Повторите подключение.', true); $('retry-bootstrap').hidden = false; }
}
$('retry-bootstrap').onclick = () => perform(bootstrap, $('retry-bootstrap'));
await bootstrap();
