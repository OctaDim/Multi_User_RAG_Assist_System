import {api, origin, reconnectMs, shortIdChars} from './api.js';
import {token} from './auth.js';
import {Drafts, tabKey} from './drafts.js';
import {textElement, messages} from './ui.js';

const $ = id => document.getElementById(id);
const unfinished = new Set(['accepted', 'searching', 'queued', 'generating']);
const labels = {accepted:'Принят', searching:'Поиск', queued:'Ожидает генерации', generating:'Ответ формируется',
  completed:'Завершён', interrupted:'Прерван', failed:'Ошибка'};
const reasons = {user_stop:'Остановлен пользователем', tab_timeout:'Соединение вкладки потеряно',
  execution_lost:'Сервис генерации остановился', source_deleted:'Источник удалён',
  unauthenticated:'Сессия завершилась', access_denied:'Доступ закрыт',
  account_changed:'Права аккаунта изменились', session_ended:'Сессия завершилась',
  search_error:'Не удалось подготовить источники', generation_error:'Не удалось сформировать ответ',
  context_limit:'Достигнут предел контекста', cancelled:'Обработка остановлена', error:'Ошибка обработки'};

export class Conversations {
  constructor(owner, reportError) {
    this.credential = token();
    this.reportError = reportError;
    this.drafts = new Drafts(owner);
    this.histories = new Map();
    this.cards = new Map();
    this.sending = new Set();
    this.questionErrors = new Map();
    this.selectionVersion = 0;
    this.documents = [];
    this.connected = false;
    this.closed = false;
    this.cursor = null;
    this.localConversation=sessionStorage.getItem('rag:new-conversation')||crypto.randomUUID();
    sessionStorage.setItem('rag:new-conversation',this.localConversation);
    this.histories.set(this.localConversation,{conversation_id:this.localConversation,requests:[],messages:[],persisted:false});
    for(const id of this.drafts.pendingConversations())if(!this.histories.has(id))
      this.histories.set(id,{conversation_id:id,requests:[],messages:[],persisted:false});
    this.selected = sessionStorage.getItem('rag:conversation')||this.localConversation;
    this.abort = new AbortController();
    $('question').oninput = () => {
      this.drafts.edit(this.selected, $('question').value);
      this.questionErrors.delete(this.selected);
      this.renderComposer(this.histories.get(this.selected), this.drafts.get(this.selected));
    };
    $('question-form').onsubmit = event => {event.preventDefault(); this.submit();};
    $('check-question').onclick = () => this.submit();
    $('new-conversation').onclick = () => this.create();
    this.connect();
  }

  current() { return !this.closed && token() === this.credential; }
  close() {
    this.closed = true;
    this.abort.abort();
    $('question').value = '';
    $('early-fragments').replaceChildren();
    $('answer-evidence').replaceChildren();
    $('grounds-indicator').hidden = true;
    $('question-sources').querySelectorAll('label').forEach(element => element.remove());
    $('answer-connection').textContent = '';
    $('active-answer-status').hidden=true;$('active-answer-actions').replaceChildren();
    this.questionErrors.clear();
    for(const id of ['question-feedback','conversation-feedback']) {$(id).textContent='';$(id).hidden=true;}
    $('new-conversation').disabled=false;$('new-conversation').removeAttribute('aria-busy');
  }

  async create() {
    const local=this.histories.get(this.localConversation);
    if(local?.requests.length||this.sending.has(this.localConversation)||this.drafts.get(this.localConversation).pending) {
      this.localConversation=crypto.randomUUID();
      sessionStorage.setItem('rag:new-conversation',this.localConversation);
      this.histories.set(this.localConversation,{conversation_id:this.localConversation,requests:[],messages:[],persisted:false});
    }
    await this.select(this.localConversation);
    document.dispatchEvent(new CustomEvent('rag:show-area',{detail:'chat'}));
    $('question').focus();
  }

  async initialize(conversations) {
    for (const value of conversations) {
      const prior=this.histories.get(value.id);
      this.histories.set(value.id,{conversation_id:value.id,requests:[],messages:[],...prior,persisted:true});
    }
    this.list();
    await this.select(this.histories.has(this.selected) ? this.selected : this.localConversation);
  }

  list() {
    $('conversations').replaceChildren();
    for (const [identifier, history] of this.histories) {
      const item = document.createElement('li');
      const first = history.messages.find(message => message.role === 'user')?.text;
      const pending=this.drafts.get(identifier).pending;
      if(!first&&!history.requests.length&&!pending)continue;
      const question=first||pending?.body.question;
      const name = `${!history.requests.length&&pending?'Не подтверждено · ':''}${question?.trim().replace(/\s+/g,' ')||'Беседа'}`;
      const button = textElement('button', name.length > 72 ? `${name.slice(0,72)}…` : name);
      button.title = name;
      button.type = 'button';
      button.dataset.conversation = identifier;
      button.setAttribute('aria-current', String(identifier === this.selected));
      button.onclick = () => {document.dispatchEvent(new CustomEvent('rag:show-area',{detail:'chat'}));this.select(identifier).catch(this.reportError);};
      item.append(button);
      $('conversations').append(item);
    }
    $('conversations-empty').hidden=Boolean($('conversations').children.length);
  }

  async select(identifier) {
    if (!identifier) return;
    const selecting=++this.selectionVersion;
    const feedback=$('conversation-feedback');
    feedback.textContent='Загружаем беседу…';feedback.dataset.error='false';feedback.hidden=false;
    this.selected = identifier;
    $('chat').dataset.conversation=identifier;
    this.cards.clear(); this.evidenceSignature = undefined;
    $('history').replaceChildren(); $('early-fragments').replaceChildren(); $('answer-evidence').replaceChildren();
    $('grounds-indicator').hidden = true;
    sessionStorage.setItem('rag:conversation', identifier);
    this.list();
    $('question').value = this.drafts.get(identifier).text;
    this.sources(this.documents);
    this.render();
    try {if(this.histories.get(identifier)?.persisted!==false)await this.refresh(identifier);}
    catch(error) {
      if(!this.current()||selecting!==this.selectionVersion)return;
      feedback.textContent=messages[error.message]||'Не удалось открыть беседу. Повторите выбор в списке.';
      feedback.dataset.error='true';throw error;
    } finally {
      if(this.current()&&selecting===this.selectionVersion&&feedback.dataset.error==='false')feedback.hidden=true;
    }
  }

  async refresh(identifier) {
    const value = await api(`/conversations/${identifier}`);
    if (!this.current()) return;
    this.install(value);
    this.list();
    if (this.selected === identifier) this.render();
  }

  install(value) {
    const prior = this.histories.get(value.conversation_id);
    const known = new Map(prior?.requests.map(request => [request.id, request]) || []);
    for (const request of value.requests) {
      if (!known.has(request.id) || known.get(request.id).version <= request.version) known.set(request.id,request);
    }
    // Retained history cannot disappear in an older read, including a read before admission.
    value.requests = Array.from(known.values());
    const messages = new Map(prior?.messages.map(message => [`${message.request_id}:${message.role}`,message]) || []);
    for (const message of value.messages) messages.set(`${message.request_id}:${message.role}`,message);
    value.messages = Array.from(messages.values());
    this.histories.set(value.conversation_id, {...value,persisted:true});
    for (const request of value.requests) this.acknowledge(value.conversation_id, request.operation_key);
  }

  acknowledge(identifier,operationKey) {
    this.drafts.accepted(identifier,operationKey);
    if(this.questionErrors.get(identifier)?.operationKey===operationKey)this.questionErrors.delete(identifier);
  }

  accepted(request, question) {
    const history = this.histories.get(request.conversation_id) || {conversation_id:request.conversation_id, requests:[], messages:[]};
    const index = history.requests.findIndex(value => value.id === request.id);
    if (index < 0) history.requests.push(request);
    else if (history.requests[index].version < request.version) history.requests[index] = request;
    if (!history.messages.some(value => value.request_id === request.id && value.role === 'user'))
      history.messages.push({request_id:request.id, role:'user', text:question});
    history.persisted=true;
    this.histories.set(request.conversation_id, history);
    this.acknowledge(request.conversation_id, request.operation_key);
  }

  sources(documents) {
    this.documents = documents;
    if (!this.selected) return;
    const selected = new Set(this.drafts.get(this.selected).documentIds);
    $('question-sources').querySelectorAll('label').forEach(element => element.remove());
    const choices = [...documents, ...Array.from(selected).filter(id => !documents.some(value => value.id === id))
      .map(id => ({id, name:this.documentName(id), unavailable:true}))];
    for (const value of choices) {
      const suffix = value.unavailable ? ' — недоступен' : value.ready ? '' : ' — ещё не готов';
      const label = textElement('label', `${value.name}${suffix}`);
      const input = document.createElement('input');
      input.type = 'checkbox'; input.value = value.id; input.checked = selected.has(value.id);
      input.onchange = () => {
        const ids = new Set(this.drafts.get(this.selected).documentIds);
        if (input.checked) ids.add(value.id); else ids.delete(value.id);
        this.drafts.selectSources(this.selected, Array.from(ids));
        this.questionErrors.delete(this.selected);
        this.render();
      };
      label.prepend(input); $('question-sources').append(label);
    }
    this.render();
  }

  effectiveSources(draft) {
    return this.documents.filter(value => value.ready && (!draft.documentIds.length || draft.documentIds.includes(value.id)));
  }

  documentName(identifier, name) {
    return name || this.documents.find(value => value.id === identifier)?.name || `Документ ${identifier.slice(0,shortIdChars)}`;
  }

  answer(card, request) {
    const text = request.answer_text || '';
    const citations = new Map((request.citations || []).map(citation => [citation.number, citation]));
    const parts = [];
    let position = 0;
    for (const match of text.matchAll(/\[source:([1-9][0-9]?)\]/g)) {
      const citation = citations.get(Number(match[1]));
      if (!citation) continue;
      parts.push(text.slice(position,match.index), citation);
      position = match.index+match[0].length;
    }
    parts.push(text.slice(position));
    for (const [index, part] of parts.entries()) {
      let node = card.answer.childNodes[index];
      const plain = typeof part === 'string';
      if (!node || (plain ? node.nodeType !== Node.TEXT_NODE : node.nodeName !== 'A' || node.dataset.citation !== String(part.number))) {
        const replacement = plain ? document.createTextNode('') : document.createElement('a');
        if (!plain) {
          replacement.dataset.citation = part.number;
          replacement.textContent = `[${part.number}]`;
          replacement.href = `#citation-${request.id}-${part.number}`;
          replacement.onclick = event => {
            event.preventDefault();
            this.showEvidence(request.id);
            const quote = $(`citation-${request.id}-${part.number}`);
            if (quote) {quote.tabIndex = -1; quote.focus({preventScroll:true}); quote.scrollIntoView({block:'nearest'});}
          };
        }
        if (node) card.answer.replaceChild(replacement,node); else card.answer.append(replacement);
        node = replacement;
      }
      if (plain && node.nodeValue !== part) node.nodeValue = part;
    }
    while (card.answer.childNodes.length > parts.length) card.answer.lastChild.remove();
  }

  showEvidence(identifier) {
    this.drafts.selectAnswer(this.selected, identifier);
    this.render();
    document.dispatchEvent(new CustomEvent('rag:show-area', {detail:'evidence'}));
  }

  async stop(request, card) {
    if (card.stopping) return;
    card.stopping = true; card.stop.disabled = true; card.feedback.textContent = '';
    try {
      await api(`/answers/${request.id}/stop`, 'POST');
      if (this.current()) await this.refresh(request.conversation_id);
    } catch (error) {
      if (this.current()) {
        card.feedback.textContent = 'Не удалось остановить ответ. Повторите попытку.';
        this.reportError(error);
      }
    } finally {
      card.stopping = false;
      if (this.current()) this.render();
    }
  }

  renderComposer(value,draft) {
    if(!this.current()||!value)return;
    if ($('question').value !== draft.text) $('question').value = draft.text;
    const ready = this.effectiveSources(draft).length;
    const busy = value.requests.some(request => unfinished.has(request.state));
    $('send-question').disabled = !this.connected || this.sending.has(this.selected) || Boolean(draft.pending) || busy || (draft.documentIds.length>0&&!ready) || !draft.text.trim();
    $('check-question').hidden = !draft.pending;
    $('check-question').disabled = !this.connected || this.sending.has(this.selected);
    const scope = draft.documentIds.length ? `Выбрано источников: ${draft.documentIds.length}. Готово для поиска: ${ready}.` : ready ? `Все готовые документы моей библиотеки: ${ready}.` : 'Без документов — ответ LLM из общих знаний.';
    const scopeLabel = `${scope}${ready||!draft.documentIds.length ? '' : ' Нет готовых источников в выбранной области. Измените выбор для отправки.'}`;
    if ($('scope-description').textContent !== scopeLabel) $('scope-description').textContent = scopeLabel;
    const summary=$('source-selection').querySelector('summary');
    const summaryLabel=draft.documentIds.length ? `Источники: выбрано ${draft.documentIds.length}` : ready ? 'Источники: все готовые' : 'Без документов · LLM';
    if(summary.textContent!==summaryLabel)summary.textContent=summaryLabel;
    const noSources=draft.documentIds.length ? ' Нет готовых документов в выборе. Измените выбор в «Источниках» или обновите статусы.' : ' Нет готовых источников. Загрузите документы или обновите их статусы.';
    const connectionStatus = !this.connected ? 'Соединение восстанавливается. Черновик сохранён.' : draft.pending ? 'Отправка пока не подтверждена. Проверьте её.' : busy ? 'В этой беседе уже выполняется запрос.' : `Соединение установлено.${!ready&&draft.documentIds.length ? noSources : !draft.text.trim() ? ' Введите вопрос.' : ''}`;
    if ($('answer-connection').textContent !== connectionStatus) $('answer-connection').textContent = connectionStatus;
    const feedback=$('question-feedback'),failure=this.questionErrors.get(this.selected);
    feedback.textContent=failure?.message||'';feedback.hidden=!failure;feedback.dataset.error='true';
  }

  render() {
    if (!this.current() || !this.selected) return;
    const value = this.histories.get(this.selected);
    if (!value) return;
    const draft = this.drafts.get(this.selected);
    this.renderComposer(value,draft);
    const title=value.messages.find(message=>message.role==='user')?.text.trim().replace(/\s+/g,' ')||'Новая беседа';
    $('conversation-title').textContent=title.length>120?title.slice(0,120)+'…':title;
    $('conversation-title').title=title;
    $('active-answer-status').hidden=!value.requests.length;
    if (!value.requests.length) {
      $('active-answer-actions').replaceChildren();
      $('history').replaceChildren(textElement('p', 'В этой беседе пока нет сообщений.'));
      this.renderEvidence(null);
      return;
    }
    if (!this.cards.size) $('history').replaceChildren();
    const questions = new Map(value.messages.filter(message => message.role === 'user').map(message => [message.request_id,message.text]));
    const selectedAnswer = value.requests.find(request => request.id === draft.answerId) || value.requests.at(-1);
    for (const request of value.requests) {
      let card = this.cards.get(request.id);
      if (!card) {
        const article = document.createElement('article'); article.dataset.request = request.id;
        const question = textElement('h3', '');
        const state = textElement('p', '');
        const answer = textElement('p', ''); answer.className = 'answer-text';
        const answerLabel = textElement('p','Ответ модели');
        const evidence = textElement('button', 'Показать основания'); evidence.type = 'button';
        evidence.setAttribute('aria-controls', 'evidence');
        evidence.onclick = () => this.showEvidence(request.id);
        const stop = textElement('button', 'Остановить ответ'); stop.type = 'button';
        const feedback = textElement('p', ''); feedback.className = 'action-feedback'; feedback.setAttribute('role','status');
        card = {article, question, state, answerLabel, answer, evidence, stop, feedback, stopping:false};
        stop.onclick = () => this.stop(request, card);
        article.append(question, state, answerLabel, answer, evidence);
        $('history').append(article);
        this.cards.set(request.id, card);
      }
      const question = questions.get(request.id) || 'Вопрос';
      if (card.question.textContent !== question) card.question.textContent = question;
      const sourceLabels = Object.entries(request.source_flags || {}).map(([identifier,flag]) =>
        `${this.documentName(identifier,request.passport?.available?.find(source=>source.document_id===identifier)?.name)}: ${flag === 'deleted' ? 'источник удалён' : 'OCR исправлен'}`);
      const stateLabel = `${labels[request.state] || request.state}${Object.hasOwn(reasons,request.reason) ? `: ${reasons[request.reason]}` : ''}${sourceLabels.length ? `. ${sourceLabels.join('; ')}. Исключён из контекста следующих ответов.` : ''}`;
      if (card.state.textContent !== stateLabel) card.state.textContent = stateLabel;
      card.answer.hidden = !request.answer_text;
      card.answerLabel.hidden = !request.answer_text;
      const citationSignature = JSON.stringify(request.citations || []);
      if (card.answerText !== request.answer_text || card.citationSignature !== citationSignature) {
        this.answer(card, request); card.answerText = request.answer_text; card.citationSignature = citationSignature;
      }
      card.stop.hidden = !unfinished.has(request.state);
      card.stop.disabled = card.stopping || !unfinished.has(request.state);
      card.evidence.setAttribute('aria-pressed', String(request.id === selectedAnswer.id));
    }
    const active=value.requests.find(request=>unfinished.has(request.state))||value.requests.at(-1);
    const activeCard=this.cards.get(active.id);
    $('active-answer-state').textContent=`Ответ: ${activeCard.state.textContent}`;
    if($('active-answer-actions').firstChild!==activeCard.stop)$('active-answer-actions').replaceChildren(activeCard.stop,activeCard.feedback);
    this.renderEvidence(selectedAnswer);
  }

  renderEvidence(request) {
    const signature = JSON.stringify([this.selected, request?.id, request?.passport, request?.citations, request?.source_flags, request?.state]);
    if (signature === this.evidenceSignature) return;
    const oldFragments = this.evidenceFragmentIds || new Set();
    this.evidenceSignature = signature;
    this.evidenceFragmentIds = new Set((request?.passport?.found || []).map(fragment => fragment.id));
    const fresh = Array.from(this.evidenceFragmentIds).some(id => !oldFragments.has(id));
    const evidenceHidden = $('evidence').hidden || (matchMedia('(max-width:1179px)').matches && $('knowledge-workspace').dataset.activeArea!=='evidence');
    if (fresh && evidenceHidden && unfinished.has(request?.state)) $('grounds-indicator').hidden = false;
    const focusedQuote=document.activeElement?.closest('#answer-evidence .cited-quote')?.id;
    const body=$('answer-evidence').closest('.area-body'),scroll=body.scrollTop;
    $('early-fragments').replaceChildren(); $('answer-evidence').replaceChildren();
    $('evidence-empty').hidden = Boolean(request);
    if (!request) return;
    const passport = request.passport || {};
    if(passport.scope_mode==='chat') {
      $('early-fragments').append(textElement('p','Ответ без поиска по документам.'));
      $('answer-evidence').append(textElement('h3','Без документов · LLM'),textElement('p','Ответ основан на общих знаниях модели и истории этой беседы. Документальные источники и цитаты не использовались.'));
      return;
    }
    const selected = passport.selected_document_ids || passport.selected || request.scope || [];
    const available = passport.available || [];
    const selectedMode = passport.scope_mode ? passport.scope_mode === 'selected' : Boolean(selected.length);
    $('answer-evidence').append(textElement('h3', 'Паспорт источников выбранного ответа'));
    $('answer-evidence').append(textElement('p', `Состояние: ${labels[request.state] || request.state}.`));
    $('answer-evidence').append(textElement('p', selectedMode ? `Область: выбранные документы. Выбрано: ${selected.map(id => this.documentName(id,available.find(value => value.document_id === id)?.name)).join(', ')}` : 'Область: все готовые документы моей библиотеки на момент отправки.'));
    $('answer-evidence').append(textElement('p', `Доступно для поиска: ${available.length ? available.map(value => this.documentName(value.document_id,value.name)).join(', ') : 'уточняется'}`));
    if (passport.excluded?.length) $('answer-evidence').append(textElement('p', `Исключены как неготовые или недоступные: ${passport.excluded.map(id => this.documentName(id)).join(', ')}`));
    if (!passport.passed) {
      $('early-fragments').append(textElement('p', 'Поиск оснований ещё не завершён.'));
      return;
    }
    $('answer-evidence').append(textElement('p', `Найдено фрагментов: ${(passport.found || []).length}. Передано модели: ${passport.passed.length}.`));
    if (passport.history_requests?.length) $('answer-evidence').append(textElement('p', `Использована история: ${passport.history_requests.length} прежних ответов. Её источники: ${(passport.history_dependencies || []).map(value => this.documentName(value.document_id)).join(', ')}`));
    for (const source of available) for (const limitation of source.limitations || [])
      $('answer-evidence').append(textElement('p', `${this.documentName(source.document_id,source.name)}: ${limitation.message}`));
    if (passport.insufficient_evidence) $('answer-evidence').append(textElement('p', 'Недостаточно найденных оснований. Это не означает, что факта нет во всей библиотеке.'));
    $('early-fragments').append(textElement('h3', unfinished.has(request.state) ? 'Найденные основания' : 'Сохранённые основания'));
    for (const fragment of passport.found || []) {
      const index = passport.passed.findIndex(value => value.id === fragment.id);
      const flag = request.source_flags?.[fragment.document_id];
      const status = flag ? flag === 'deleted' ? ' · Источник удалён' : ' · OCR исправлен; первоначальный фрагмент' : '';
      $('early-fragments').append(textElement('p', `${this.documentName(fragment.document_id,fragment.name)} · Страница ${fragment.page} · ${index>=0 ? `Передан модели [${index+1}]` : 'Не передан модели из-за объёма контекста'}${status}`));
      const quote = textElement('blockquote', fragment.text); quote.dataset.fragment = fragment.id;
      $('early-fragments').append(quote);
    }
    for (const citation of request.citations || []) {
      const flag = request.source_flags?.[citation.document_id];
      $('answer-evidence').append(textElement('h4', `Цитата [${citation.number}]: ${this.documentName(citation.document_id,citation.name)} · Страница ${citation.page}${flag ? ` · ${flag === 'deleted' ? 'Источник удалён' : 'OCR исправлен; первоначальная цитата'}` : ''}`));
      const quote = textElement('blockquote', citation.quote); quote.className = 'cited-quote'; quote.id = `citation-${request.id}-${citation.number}`;
      $('answer-evidence').append(quote);
    }
    const quote=focusedQuote&&$(focusedQuote);
    if(quote){quote.tabIndex=-1;quote.focus({preventScroll:true});body.scrollTop=scroll;}
  }

  async submit() {
    if (!this.current() || !this.connected || this.sending.has(this.selected)) return;
    const identifier = this.selected;
    const draft = this.drafts.get(identifier);
    if (!draft.pending && draft.documentIds.length && !this.effectiveSources(draft).length) {
      this.questionErrors.set(identifier,{message:messages.no_ready_sources});this.render();
      this.reportError(new Error('no_ready_sources'));return;
    }
    if (!draft.pending && !draft.text.trim()) return;
    const pending = this.drafts.begin(identifier, {operation_key:crypto.randomUUID(), question:draft.text,
      document_ids:draft.documentIds, tab_id:this.tab.id});
    this.questionErrors.delete(identifier);
    this.sending.add(identifier); this.render();
    try {
      if(this.histories.get(identifier)?.persisted===false) {
        await api('/conversations','POST',{id:identifier});
        if(!this.current())return;
        this.histories.get(identifier).persisted=true;
      }
      const request = await api(`/conversations/${identifier}/answers`, 'POST', pending.body, {'X-Tab-Proof':this.tab.proof});
      if (!this.current()) return;
      this.accepted(request, pending.body.question);
      this.list();
      if (this.selected === identifier) $('question').value = this.drafts.get(identifier).text;
    } catch (error) {
      if (!this.current()) return;
      if(this.drafts.get(identifier).pending?.body.operation_key!==pending.body.operation_key)return;
      if (['conversation_busy','no_ready_sources','invalid_scope','coordinator_unavailable','tab_disconnected','invalid_input','context_too_large','tokenizer_unavailable'].includes(error.message)) this.drafts.rejected(identifier, pending.body.operation_key);
      this.questionErrors.set(identifier,{operationKey:pending.body.operation_key,
        message:messages[error.message]||'Не удалось отправить вопрос. Проверьте отправку перед повтором.'});
      this.reportError(error);
    } finally {
      this.sending.delete(identifier);
      if(this.current()){this.list();this.render();}
    }
  }

  async connect() {
    try {
      this.tab = JSON.parse(sessionStorage.getItem(tabKey) || 'null');
      if (!this.tab) {
        this.tab = await api('/tabs', 'POST');
        if (!this.current()) return;
        sessionStorage.setItem(tabKey, JSON.stringify(this.tab));
      }
      while (this.current()) {
        let reader;
        try {
          const headers = {Authorization:`Bearer ${this.credential}`, 'X-Tab-Proof':this.tab.proof};
          if (this.cursor !== null) headers['Last-Event-ID'] = String(this.cursor);
          const response = await fetch(`${origin}/api/tabs/${this.tab.id}/events`, {headers, signal:this.abort.signal});
          if (!response.ok) throw new Error((await response.json()).error || 'request_failed');
          reader = response.body.getReader();
          const decoder = new TextDecoder('utf-8', {fatal:true});
          let buffer = '';
          while (this.current()) {
            const part = await reader.read();
            if (part.done) break;
            buffer += decoder.decode(part.value, {stream:true});
            let boundary;
            while ((boundary = buffer.indexOf('\n\n')) >= 0) {
              const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary+2);
              const data = frame.split('\n').find(line => line.startsWith('data: '));
              if (data) await this.receive(JSON.parse(data.slice(6)));
            }
          }
        } catch (error) {
          if (!this.current()) return;
          if (['unauthenticated','access_denied','invalid_tab'].includes(error.message)) throw error;
        } finally {
          if (reader) await reader.cancel().catch(() => {});
        }
        this.connected = false; this.render();
        await new Promise(resolve => setTimeout(resolve, reconnectMs));
      }
    } catch (error) {if (this.current()) this.reportError(error);}
  }

  async receive(value) {
    if (!this.current()) return;
    if (value.kind === 'heartbeat') {
      await api(`/tabs/${this.tab.id}/heartbeat`, 'POST', undefined, {'X-Tab-Proof':this.tab.proof,
        'X-Connection-Epoch':String(value.payload.connection_epoch), 'X-Heartbeat-Challenge':value.payload.challenge});
      if(!this.connected){this.connected=true;this.render();} return;
    }
    if (this.cursor !== null && value.id <= this.cursor) return;
    if (value.kind === 'snapshot') {
      for (const history of value.payload.conversations) this.install(history);
      this.list(); this.render();
    } else {
      if (value.kind === 'accepted') {
        this.accepted({id:value.request_id, conversation_id:value.conversation_id,
          state:value.payload.state, version:value.payload.version, operation_key:value.payload.operation_key,
          scope:value.payload.scope, created_at:value.payload.created_at, answer_text:'', passport:value.payload.passport || {}}, value.payload.question);
      } else {
        const history = this.histories.get(value.conversation_id);
        const request = history?.requests.find(request => request.id === value.request_id);
        if (!request) {this.cursor = null; throw new Error('missing_request');}
        if (value.kind === 'invalidated') {
          await this.refresh(value.conversation_id);
          this.cursor = value.id;
          return;
        }
        if (value.payload.version > request.version) {
          if (value.payload.version !== request.version+1) {this.cursor = null; throw new Error('missing_request_version');}
          if (value.payload.source_flags) request.source_flags = value.payload.source_flags;
          if (Object.hasOwn(value.payload,'excluded')) request.excluded = value.payload.excluded;
          if (value.kind === 'output') {request.answer_text += value.payload.text; request.citations = value.payload.citations || [];}
          else if (value.kind === 'fragments') {request.passport = value.payload.passport; request.state = 'queued';}
          else if (value.kind === 'state' || value.kind === 'terminal' || value.kind === 'source_status') {request.state = value.payload.state; request.reason = value.payload.reason;}
          request.version = value.payload.version;
        }
      }
      if (value.kind === 'accepted') this.list();
      if (this.selected === value.conversation_id) this.render();
    }
    this.cursor = value.id;
  }
}
