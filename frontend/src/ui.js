export const roleLabels={user:'Пользователь',admin:'Администратор',super_admin:'Суперадминистратор'};
export const messages = {
  request_timeout: 'Время ожидания истекло. Результат записи может быть неизвестен. Обновите состояние перед повтором.',
  network_error: 'Соединение прервано. Результат записи может быть неизвестен. Проверьте состояние перед повтором.',
  invalid_scope: 'Выбранный источник недоступен. Проверьте выбор документов; область поиска не расширена.',
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
  no_ready_sources: 'Нет готовых источников в выбранной области. Вопрос сохранён как черновик.',
  conversation_busy: 'В этой беседе уже выполняется запрос. Черновик сохранён.',
  coordinator_unavailable: 'Сервис ответов сейчас недоступен. Черновик сохранён.',
  context_too_large: 'Вопрос превышает доступный контекст модели. Сократите вопрос; текст сохранён как черновик.',
  tokenizer_unavailable: 'Не удалось проверить объём вопроса. Сервис модели временно недоступен; черновик сохранён.',
  invalid_settings: 'Укажите положительные целые значения изменяемых настроек. Параметры перезапуска доступны только для просмотра.',
  document_not_ready: 'Документ ещё не готов. Обновите его статус после обработки.',
  document_worker_lost: 'Обработка прервана из-за остановки сервиса. Оригинал сохранён; автоматического повтора нет.',
  document_processing_failed: 'Не удалось обработать документ.',
  upload_failed: 'Загрузка документа не завершена.',
  filename_too_long: 'Имя файла превышает разрешённую длину.',
  invalid_utf8: 'Текст документа не является корректным UTF-8.',
  invalid_docx: 'Структура файла DOCX повреждена.',
  pdf_page_limit: 'Число страниц PDF превышает разрешённый предел.',
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

export function status(value, error = false) {
  const element = document.getElementById('status');
  element.textContent = value; element.dataset.error = String(error);
}
export function feedback(control, value, error = false) {
  if (!control?.isConnected) return;
  const target = control.closest('form, li, article, section') || control.parentElement;
  let output = Array.from(target.children).find(element => element.classList.contains('operation-status'));
  if (!output) {output = document.createElement('p'); output.className = 'operation-status'; output.setAttribute('role','status'); output.setAttribute('aria-live','polite'); target.append(output);}
  output.textContent = value; output.dataset.error = String(error);
}
export function textElement(tag, text) {
  const element = document.createElement(tag); element.textContent = text; return element;
}
export function confirmAction(title, description, acceptLabel = 'Продолжить') {
  const dialog = document.getElementById('confirm-action');
  if (dialog.open) return Promise.resolve(false);
  const previous = document.activeElement;
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-description').textContent = description;
  document.getElementById('confirm-accept').textContent = acceptLabel;
  return new Promise(resolve => {
    document.getElementById('confirm-cancel').onclick = () => dialog.close('cancel');
    document.getElementById('confirm-accept').onclick = () => dialog.close('accept');
    dialog.returnValue = 'cancel';
    dialog.addEventListener('close', () => {previous?.isConnected && previous.focus({preventScroll:true}); resolve(dialog.returnValue === 'accept');}, {once:true});
    dialog.showModal(); document.getElementById('confirm-cancel').focus();
  });
}
