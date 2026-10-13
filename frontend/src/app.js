import { api } from './api.js';
import { token, signIn, signOut } from './auth.js';

const $ = id => document.getElementById(id);
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
};

function status(value) { $('status').textContent = value; }

async function perform(operation, control) {
  if (control) control.disabled = true;
  try { await operation(); }
  catch (error) {
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
    $('accounts').append(form);
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
