import { api, publicSettings } from './api.js';
import {Documents} from './documents.js';
import { token, signIn, signOut } from './auth.js';
import {Conversations, textElement} from './conversations.js';
import {messages, status, feedback} from './ui.js';
import {configureNavigation, showSection, showArea, resetNavigation} from './navigation.js';

const $ = id => document.getElementById(id);
let conversations;
let workspaceRead=0;
let settingsRead = 0;
let inputPolicy;
const documents = new Documents({perform, onSources:files=>conversations?.sources(files), inputPolicy:()=>inputPolicy, reveal:()=>showArea('library')});
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
  $('accounts').replaceChildren();
  $('global-settings').replaceChildren();
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
  $('identity').textContent = `${current.account.email} · ${current.account.role}`;
  if (!conversations) conversations = new Conversations(current.account.id, error => perform(() => {throw error;}));
  await conversations.initialize(current.conversations);
  if(reading!==workspaceRead)return;
  if (current.account.role !== 'user') await perform(() => showAccounts(current.account.role));
  $('generation-settings').hidden = current.account.role !== 'super_admin';
  if (current.account.role === 'super_admin') await perform(showSettings);
  if(reading!==workspaceRead)return;
  await perform(()=>documents.load(null,'',false), $('refresh-documents'));
}

async function showAccounts(actorRole) {
  const accounts = await api('/accounts');
  $('accounts').replaceChildren();
  for (const account of accounts) {
    const form = document.createElement('form');
    form.dataset.account = account.email;
    form.append(textElement('h3', account.email || 'Аккаунт без email'));
    const roleLabel = textElement('label', 'Роль');
    const role = document.createElement('select');
    role.name = 'role';
    for (const value of ['user', 'admin', 'super_admin']) {
      const option = textElement('option', value);
      option.value = value;
      role.append(option);
    }
    role.value = account.role;
    role.disabled = actorRole !== 'super_admin';
    roleLabel.append(role);
    form.append(roleLabel);
    for (const [key, label] of [['active', 'Аккаунт активен'], ['disabled', 'Административная блокировка']]) {
      const input = document.createElement('input');
      input.type = 'checkbox'; input.name = key; input.checked = account[key];
      const field = textElement('label', label);
      field.append(input);
      form.append(field);
    }
    const submit = textElement('button', 'Сохранить права');
    submit.disabled = actorRole === 'admin' && account.role !== 'user';
    form.append(submit);
    form.addEventListener('submit', event => {
      event.preventDefault();
      perform(async () => {
        const changes = { active: form.elements.active.checked, disabled: form.elements.disabled.checked };
        if (actorRole === 'super_admin') changes.role = role.value;
        await api(`/accounts/${account.id}`, 'PATCH', changes);
        status('Права сохранены.');
        await showWorkspace();
      }, submit);
    });
    const card=document.createElement('article');card.append(form);
    const details=document.createElement('details');
    details.append(textElement('summary','Ограничения и разрешения документов'));
    const policyForm=document.createElement('form');policyForm.dataset.policy=account.id;
    details.append(policyForm);card.append(details);
    let loading=false;
    details.addEventListener('toggle',()=>{
      if (!details.open || loading || policyForm.childNodes.length) return;
      loading=true;
      perform(async()=>{
        const value=await api(`/documents/policies/${account.id}`);
        const limits={file_bytes:'Размер одного файла (байт)',pdf_pages:'Страницы PDF',batch_files:'Файлы в одной загрузке',documents:'Общее число документов',original_bytes:'Объём оригиналов (байт)'};
        const permissions={pdf:'PDF',docx:'DOCX',txt:'TXT',md:'Markdown',handwriting:'OCR рукописей'};
        for (const [key,label] of Object.entries(limits)) {
          const field=textElement('label',label);const input=document.createElement('input');
          input.name=key;input.type='number';input.min='1';input.step='1';input.value=value.limits[key];input.required=true;
          field.append(input);policyForm.append(field);
        }
        for (const [key,label] of Object.entries(permissions)) {
          const field=textElement('label',label);const input=document.createElement('input');
          input.name=key;input.type='checkbox';input.checked=value.permissions[key];field.append(input);policyForm.append(field);
        }
        const save=textElement('button','Сохранить ограничения документов');policyForm.append(save);
        policyForm.addEventListener('submit',event=>{
          event.preventDefault();
          perform(async()=>{
            const changed={limits:{},permissions:{}};
            for (const key of Object.keys(limits)) {
              const number=Number(policyForm.elements[key].value);
              if (!Number.isSafeInteger(number) || number<1) throw new Error('invalid_document_policy');
              changed.limits[key]=number;
            }
            for (const key of Object.keys(permissions)) changed.permissions[key]=policyForm.elements[key].checked;
            await api(`/documents/policies/${account.id}`,'PATCH',changed);
            status('Ограничения документов сохранены.');
          },save);
        });
      }).finally(()=>{loading=false;});
    });
    if (actorRole==='super_admin') {
      const library=textElement('button','Читать библиотеку');library.type='button';
      library.addEventListener('click',()=>perform(()=>documents.load(account.id,account.email),library));card.append(library);
    }
    $('accounts').append(card);
  }
}

async function showSettings() {
  const reading = ++settingsRead;
  const value = await api('/settings');
  if (reading !== settingsRead) return;
  const form = $('global-settings');
  form.replaceChildren();
  const revision = textElement('p', `Сохранена ревизия ${value.revision}. ${value.applied_revision === value.revision ? 'Применена' : 'Ожидает применения'}: ${value.applied_revision}.`);
  revision.className = 'settings-revision';
  form.append(revision);
  const labels = {max_active:'Активные запросы', step_width:'Запросы за шаг', model:'Модель генерации',
    n_ctx:'Контекст запроса', n_threads:'Потоки генерации', n_threads_batch:'Потоки обработки prompt', thinking:'Thinking'};
  for (const [key, current] of Object.entries(value.values)) {
    const label = textElement('label', labels[key] || key);
    const input = document.createElement('input'); input.name = key;
    input.type = value.mutable.includes(key) ? 'number' : 'text';
    input.value = String(current); input.disabled = !value.mutable.includes(key);
    if (!input.disabled) {input.min = '1'; input.step = '1'; input.required = true;}
    label.append(input); form.append(label);
  }
  form.append(textElement('p', `Эмбеддинги: ${value.embedding.model}, ${value.embedding.backend}, ${value.embedding.quantization}. Параметры модели и эмбеддингов требуют перезапуска и доступны только для просмотра.`));
  const preview = textElement('div', ''); preview.className = 'settings-preview'; preview.setAttribute('aria-live','polite');
  const inspect = textElement('button', 'Предпросмотр изменения'); inspect.type = 'submit';
  const save = textElement('button', 'Сохранить глобальные настройки'); save.type = 'button'; save.hidden = true;
  const refresh = textElement('button', 'Обновить применение настроек'); refresh.type = 'button';
  let proposed;
  form.oninput = () => {proposed = undefined; save.hidden = true; preview.replaceChildren();};
  form.onsubmit = event => {
    event.preventDefault();
    perform(async () => {
      proposed = {};
      for (const key of value.mutable) {
        const number = Number(form.elements[key].value);
        if (!Number.isSafeInteger(number) || number < 1) throw new Error('invalid_settings');
        proposed[key] = number;
      }
      preview.replaceChildren(textElement('p', 'Область действия: весь сервис, все API-процессы.'));
      for (const key of value.mutable) preview.append(textElement('p', `${labels[key]}: ${value.values[key]} → ${proposed[key]}`));
      preview.append(textElement('p', 'Уменьшение лимита сохраняет уже активные ответы; новые ждут свободного места. Новые значения действуют после применения координатором и сохраняются после перезапуска. Скорость выдачи и расход памяти при новых значениях неизвестны.'));
      save.hidden = false;
    }, inspect);
  };
  save.addEventListener('click', () => perform(async () => {
    if (!proposed) return;
    ++settingsRead;
    form.inert = true;
    try {
      const saved = await api('/settings','PATCH',proposed);
      status(`Ревизия ${saved.revision} сохранена. Применённая ревизия: ${saved.applied_revision}.`);
      await showSettings();
    } finally { form.inert = false; }
  },save));
  refresh.addEventListener('click', () => perform(showSettings,refresh));
  form.append(inspect, preview, save, refresh);
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
