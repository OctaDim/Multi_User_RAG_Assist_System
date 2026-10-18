import {api} from './api.js';
import {textElement, status, roleLabels} from './ui.js';
const $=id=>document.getElementById(id);
export function createAdministration({perform,openLibrary}) {
let settingsRead=0,accountsRead=0,actorRole='';
$('refresh-administration').onclick=()=>perform(async()=>{await showAccounts(actorRole);if(actorRole==='super_admin')await showSettings();},$('refresh-administration'));
async function showAccounts(role) {
  actorRole=role;$('refresh-administration').disabled=false;
  const reading=++accountsRead;
  const accounts = await api('/accounts');
  if(reading!==accountsRead)return;
  $('accounts').replaceChildren();
  for (const account of accounts) {
    const form = document.createElement('form');
    form.dataset.account = account.email;
    form.append(textElement('h4', account.email || 'Аккаунт без email'));
    const roleLabel = textElement('label', 'Роль');
    const role = document.createElement('select');
    role.name = 'role';
    for (const value of ['user', 'admin', 'super_admin']) {
      const option = textElement('option', roleLabels[value]);
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
        await showAccounts(actorRole);
      }, submit);
    });
    const card=document.createElement('article');card.append(form);
    const details=document.createElement('details');
    details.append(textElement('summary','Ограничения и разрешения документов'));
    const policyForm=document.createElement('form');policyForm.dataset.policy=account.id;
    details.append(policyForm);card.append(details);
    let loading=false,loaded=false;
    const retry=textElement('button','Повторить загрузку ограничений');retry.type='button';retry.hidden=true;policyForm.append(retry);
    const loadPolicy=()=>{
      if(loading||loaded)return;
      loading=true;retry.hidden=true;
      perform(async()=>{
        const value=await api(`/documents/policies/${account.id}`);
        if(reading!==accountsRead||!policyForm.isConnected)return;
        policyForm.replaceChildren();loaded=true;
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
      },retry).finally(()=>{loading=false;if(!loaded)retry.hidden=false;});
    };
    details.addEventListener('toggle',()=>{if(details.open)loadPolicy();});
    retry.onclick=loadPolicy;
    if (actorRole==='super_admin') {
      const library=textElement('button','Читать библиотеку');library.type='button';
      library.addEventListener('click',()=>perform(()=>openLibrary(account.id,account.email),library));card.append(library);
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


return {accounts:showAccounts,settings:showSettings,clear(){actorRole='';$('refresh-administration').disabled=true;++settingsRead;++accountsRead;$('accounts').replaceChildren();$('global-settings').replaceChildren();}};
}
