import { api } from './api.js';
import { token, signIn, signOut } from './auth.js';

const $ = id => document.getElementById(id);
const documentURLs = new Set();
const messages = {
  invalid_credentials: 'Неверный email или пароль.',
  access_denied: 'Доступ закрыт. Подтвердите email или обратитесь к администратору.',
  registration_conflict: 'Регистрация этого email недоступна.',
  invalid_verification: 'Ссылка подтверждения недействительна или уже использована.',
  invalid_invitation: 'Приглашение недействительно.',
  mail_delivery_failed: 'Письмо не доставлено. Повторите регистрацию с тем же паролем.',
  mail_not_configured: 'Отправка почты не настроена.',
  frontend_not_configured: 'Адрес веб-интерфейса не настроен.',
  forbidden: 'Недостаточно прав.',
  unauthenticated: 'Сессия завершилась. Войдите снова.',
  document_not_ready: 'Документ ещё не готов. Обновите его статус после обработки.',
  document_worker_lost: 'Обработка прервана из-за остановки сервиса. Оригинал сохранён; автоматического повтора нет.',
  document_format_forbidden: 'Загрузка этого формата не разрешена для вашей учётной записи.',
  document_permission_revoked: 'Разрешение на эту обработку отозвано.',
  file_size_limit: 'Файл превышает допустимый размер.',
  batch_limit: 'Выбрано больше файлов, чем разрешено в одной загрузке.',
  document_storage_limit: 'Превышен лимит числа документов или объёма оригиналов.',
  original_storage_not_configured: 'Хранилище документов не настроено.',
  document_revision_changed: 'Ревизия уже изменилась. Откройте документ заново перед исправлением.',
  skip_marker_required: 'Блоки пропущенных рукописей нужно сохранить.',
  invalid_document_policy: 'Укажите положительные целые лимиты и разрешения документов.',
};

function status(value) { $('status').textContent = value; }

async function perform(operation, control) {
  if (control) control.disabled = true;
  try { await operation(); }
  catch (error) {
    if (error.message === 'session_changed') return;
    status(messages[error.message] || 'Не удалось выполнить действие.');
    // SMTP failure follows committed registration, which already consumed the invite.
    if (error.message === 'mail_delivery_failed') $('register').elements.invitation.value = '';
    if (error.message === 'unauthenticated' || error.message === 'access_denied') {
      signOut();
      showAuthentication();
    }
  } finally { if (control) control.disabled = false; }
}

function showAuthentication() {
  $('authentication').hidden = false;
  $('workspace').hidden = true;
  $('identity').textContent = '';
  $('history').replaceChildren();
  $('conversations').replaceChildren();
  $('accounts').replaceChildren();
  clearDocumentView();
  $('documents').replaceChildren();
  $('document-upload').reset();
}

function textElement(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

async function showWorkspace() {
  const current = await api('/accounts/me');
  $('authentication').hidden = true;
  $('workspace').hidden = false;
  $('identity').textContent = `${current.account.email} · ${current.account.role}`;
  $('conversations').replaceChildren();
  for (const conversation of current.conversations) {
    const button = textElement('button', 'Открыть беседу');
    button.type = 'button';
    button.addEventListener('click', () => perform(async () => {
      const history = await api(`/conversations/${conversation.id}`);
      $('history').replaceChildren(...(history.messages.length
        ? history.messages.map(message => textElement('p', message.text))
        : [textElement('p', 'В этой беседе пока нет сообщений.')]));
    }, button));
    const item = document.createElement('li');
    item.append(button);
    $('conversations').append(item);
  }
  $('administration').hidden = current.account.role === 'user';
  if (current.account.role !== 'user') await showAccounts(current.account.role);
  await showLibrary();
}

function clearDocumentView() {
  for (const url of documentURLs) URL.revokeObjectURL(url);
  documentURLs.clear();
  $('document-view').replaceChildren();
}

async function showLibrary(ownerId) {
  const result = await api(ownerId ? `/documents/admin/${ownerId}/library` : '/documents');
  clearDocumentView();
  $('document-upload').hidden = result.readonly;
  $('documents').replaceChildren();
  const labels = {receiving:'Загрузка',queued:'Ожидает обработки',processing:'Обрабатывается',awaiting_choice:'Нужен выбор режима',ready:'Готов',failed:'Обработка неуспешна',cancelled:'Отменён'};
  for (const file of result.documents) {
    const item = document.createElement('li');
    item.dataset.document = file.id;
    item.append(textElement('strong',file.name),textElement('p',labels[file.state]));
    if (file.error) item.append(textElement('p',`${messages[file.error] || file.error}${file.failure_page ? ` · страница ${file.failure_page}` : ''}`));
    if (file.ready) {
      const open = textElement('button','Открыть документ');
      open.type='button';
      open.addEventListener('click',()=>perform(()=>showDocument(file,result.readonly),open));
      item.append(open);
    }
    if (!result.readonly && file.state==='awaiting_choice') {
      item.append(textElement('p','Для вашей учётной записи OCR рукописей не разрешён. Можно отменить загрузку документа или продолжить с пропуском рукописного текста.'));
      for (const [choice,label] of [['skip_handwriting','Загрузить только печатный текст'],['cancel','Отменить весь документ']]) {
        const button = textElement('button',label); button.type='button';
        button.addEventListener('click',()=>perform(async()=>{await api(`/documents/${file.id}/mode`,'POST',{choice});await showLibrary();},button));
        item.append(button);
      }
    }
    if (!result.readonly) {
      const remove=textElement('button','Удалить документ'); remove.type='button';
      remove.addEventListener('click',()=>perform(async()=>{await api(`/documents/${file.id}`,'DELETE');await showLibrary();},remove));
      item.append(remove);
    }
    $('documents').append(item);
  }
}

async function showDocument(file,readonly) {
  const value=await api(`/documents/${file.id}`);
  clearDocumentView();
  const view=$('document-view');
  view.append(textElement('h3',file.name));
  const original=textElement('button','Скачать оригинал'); original.type='button';
  original.addEventListener('click',()=>perform(async()=>{
    const blob=await api(`/documents/${file.id}/original`);
    const url=URL.createObjectURL(blob);documentURLs.add(url);
    const link=document.createElement('a');link.href=url;link.download=file.name;link.click();
  },original));
  view.append(original,textElement('p','Распознанный текст можно проверить и исправить. Оригинал сохраняется.'));
  const form=document.createElement('form');form.id='document-correction';
  for (const page of value.pages) {
    const section=document.createElement('section');section.className='document-page';
    const label=textElement('label',file.format==='pdf' ? `Страница ${page.page}: текст` : 'Текст документа');
    const text=document.createElement('textarea');text.name=`page-${page.page}`;text.dataset.page=page.page;text.value=page.text;text.rows=12;text.readOnly=readonly;
    label.append(text);section.append(label);
    if (file.format==='pdf') {
      const blob=await api(`/documents/${file.id}/pages/${page.page}/original`);
      const url=URL.createObjectURL(blob);documentURLs.add(url);
      const figure=document.createElement('figure');figure.className='original-page';
      const image=document.createElement('img');image.src=url;image.alt=`Оригинал страницы ${page.page}`;
      image.addEventListener('load',()=>{
        for (const region of page.regions.filter(region=>region.kind==='skip' && region.bbox)) {
          const marker=textElement('span','Пропуск');marker.className='skip-region';marker.title=region.text;
          const [x0,y0,x1,y1]=region.bbox;
          marker.style.left=`${x0/image.naturalWidth*100}%`;marker.style.top=`${y0/image.naturalHeight*100}%`;
          marker.style.width=`${(x1-x0)/image.naturalWidth*100}%`;marker.style.height=`${(y1-y0)/image.naturalHeight*100}%`;
          figure.append(marker);
        }
      });
      figure.append(image);section.prepend(figure);
    }
    form.append(section);
  }
  if (!readonly) {
    const save=textElement('button','Сохранить исправления');form.append(save);
    form.addEventListener('submit',event=>{
      event.preventDefault();
      perform(async()=>{
        const pages=Array.from(form.querySelectorAll('textarea')).map(input=>({page:Number(input.dataset.page),text:input.value}));
        await api(`/documents/${file.id}/corrections`,'POST',{base_revision:value.document.published_revision,pages});
        status('Исправления приняты. Новая ревизия появится после полной индексации.');
        await showLibrary();
      },save);
    });
    if (file.format==='pdf') {
      const full=textElement('button','Обработать PDF полностью');full.type='button';
      full.addEventListener('click',()=>perform(async()=>{await api(`/documents/${file.id}/mode`,'POST',{choice:'complete'});await showLibrary();},full));
      view.append(full);
    }
  }
  view.append(form);
}

$('document-upload').addEventListener('submit',event=>{
  event.preventDefault();
  const form=event.currentTarget;
  perform(async()=>{
    const files=Array.from(form.elements.files.files);
    const batch=await api('/documents/uploads','POST',{files:files.map(file=>({name:file.name,size:file.size}))});
    for (let index=0;index<batch.documents.length;index++) await api(`/documents/${batch.documents[index].id}/original`,'PUT',files[index]);
    form.reset();status('Файлы приняты. Обработка выполняется в фоне.');await showLibrary();
  },form.querySelector('button'));
});
$('refresh-documents').addEventListener('click',()=>perform(()=>showLibrary(),$('refresh-documents')));

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
      library.addEventListener('click',()=>perform(()=>showLibrary(account.id),library));card.append(library);
    }
    $('accounts').append(card);
  }
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
if (fragment.has('invite')) $('register').elements.invitation.value = fragment.get('invite');
if (fragment.has('verify')) await perform(async () => {
  await api('/accounts/verify', 'POST', { token: fragment.get('verify') });
  status('Email подтверждён. Теперь войдите.');
});
if (token()) await perform(showWorkspace);
document.documentElement.dataset.ready = 'true';
