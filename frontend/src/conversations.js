import {api, origin} from './api.js';
import {token} from './auth.js';
import {Drafts, tabKey} from './drafts.js';

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

export function textElement(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

export class Conversations {
  constructor(owner, reportError) {
    this.credential = token();
    this.reportError = reportError;
    this.drafts = new Drafts(owner);
    this.histories = new Map();
    this.cards = new Map();
    this.sending = new Set();
    this.documents = [];
    this.connected = false;
    this.closed = false;
    this.cursor = null;
    this.selected = sessionStorage.getItem('rag:conversation');
    this.abort = new AbortController();
    $('question').oninput = () => this.drafts.edit(this.selected, $('question').value);
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
    $('question-sources').querySelectorAll('label').forEach(element => element.remove());
    $('answer-connection').textContent = '';
  }

  async create() {
    $('new-conversation').disabled = true;
    try {
      const value = await api('/conversations', 'POST');
      if (!this.current()) return;
      this.histories.set(value.id, {conversation_id:value.id, requests:[], messages:[]});
      this.list();
      await this.select(value.id);
    } catch (error) { this.reportError(error); }
    finally {$('new-conversation').disabled = false;}
  }

  async initialize(conversations) {
    for (const value of conversations) {
      if (!this.histories.has(value.id)) this.histories.set(value.id, {conversation_id:value.id, requests:[], messages:[]});
    }
    this.list();
    await this.select(this.histories.has(this.selected) ? this.selected : conversations[0]?.id);
  }

  list() {
    $('conversations').replaceChildren();
    for (const [identifier] of this.histories) {
      const item = document.createElement('li');
      const button = textElement('button', 'Открыть беседу');
      button.type = 'button';
      button.dataset.conversation = identifier;
      button.setAttribute('aria-current', String(identifier === this.selected));
      button.onclick = () => this.select(identifier).catch(this.reportError);
      item.append(button);
      $('conversations').append(item);
    }
  }

  async select(identifier) {
    if (!identifier) return;
    this.selected = identifier;
    this.cards.clear(); this.fragmentSignature = undefined;
    $('history').replaceChildren(); $('early-fragments').replaceChildren();
    sessionStorage.setItem('rag:conversation', identifier);
    this.list();
    $('question').value = this.drafts.get(identifier).text;
    this.render();
    await this.refresh(identifier);
  }

  async refresh(identifier) {
    const value = await api(`/conversations/${identifier}`);
    if (!this.current()) return;
    this.install(value);
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
    this.histories.set(value.conversation_id, value);
    for (const request of value.requests) this.drafts.accepted(value.conversation_id, request.operation_key);
  }

  accepted(request, question) {
    const history = this.histories.get(request.conversation_id) || {conversation_id:request.conversation_id, requests:[], messages:[]};
    const index = history.requests.findIndex(value => value.id === request.id);
    if (index < 0) history.requests.push(request);
    else if (history.requests[index].version < request.version) history.requests[index] = request;
    if (!history.messages.some(value => value.request_id === request.id && value.role === 'user'))
      history.messages.push({request_id:request.id, role:'user', text:question});
    this.histories.set(request.conversation_id, history);
    this.drafts.accepted(request.conversation_id, request.operation_key);
  }

  sources(documents) {
    this.documents = documents;
    const selected = new Set(Array.from($('question-sources').querySelectorAll('input:checked'), input => input.value));
    $('question-sources').querySelectorAll('label').forEach(element => element.remove());
    for (const value of documents) {
      const label = textElement('label', `${value.name}${value.ready ? '' : ' — ещё не готов'}`);
      const input = document.createElement('input');
      input.type = 'checkbox'; input.value = value.id; input.checked = selected.has(value.id);
      label.prepend(input); $('question-sources').append(label);
    }
  }

  documentName(identifier, name) {
    return name || this.documents.find(value => value.id === identifier)?.name || `Документ ${identifier.slice(0,8)}`;
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
          replacement.onclick = () => {card.passport.open = true;};
        }
        if (node) card.answer.replaceChild(replacement,node); else card.answer.append(replacement);
        node = replacement;
      }
      if (plain && node.nodeValue !== part) node.nodeValue = part;
    }
    while (card.answer.childNodes.length > parts.length) card.answer.lastChild.remove();
  }

  render() {
    if (!this.current() || !this.selected) return;
    const value = this.histories.get(this.selected);
    const draft = this.drafts.get(this.selected);
    if ($('question').value !== draft.text) $('question').value = draft.text;
    $('send-question').disabled = !this.connected || this.sending.has(this.selected) || Boolean(draft.pending) || value.requests.some(request => unfinished.has(request.state));
    $('check-question').hidden = !draft.pending;
    $('check-question').disabled = !this.connected || this.sending.has(this.selected);
    const connectionStatus = this.connected ? (draft.pending ? 'Отправка пока не подтверждена. Проверьте её.' : 'Соединение установлено.') : 'Соединение восстанавливается. Черновик сохранён.';
    if ($('answer-connection').textContent !== connectionStatus) $('answer-connection').textContent = connectionStatus;
    if (!value.requests.length) {
      $('history').replaceChildren(textElement('p', 'В этой беседе пока нет сообщений.'));
      return;
    }
    if (!this.cards.size) $('history').replaceChildren();
    const questions = new Map(value.messages.filter(message => message.role === 'user').map(message => [message.request_id,message.text]));
    for (const request of value.requests) {
      let card = this.cards.get(request.id);
      if (!card) {
        const article = document.createElement('article'); article.dataset.request = request.id;
        const question = textElement('h3', '');
        const state = textElement('p', '');
        const answer = textElement('p', ''); answer.className = 'answer-text';
        const answerLabel = textElement('p','Ответ модели');
        const passport = document.createElement('details'); passport.className = 'answer-passport';
        passport.append(textElement('summary', 'Паспорт источников'));
        const contents = document.createElement('div'); passport.append(contents);
        const stop = textElement('button', 'Остановить ответ'); stop.type = 'button';
        stop.onclick = async () => {
          stop.disabled = true;
          try {await api(`/answers/${request.id}/stop`, 'POST'); await this.refresh(request.conversation_id);}
          catch (error) {this.reportError(error);}
        };
        const quotes = document.createElement('div'); passport.append(quotes);
        article.append(question, state, answerLabel, answer, passport, stop);
        $('history').append(article);
        card = {article, question, state, answerLabel, answer, passport, contents, quotes, stop};
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
      const citationSignature = JSON.stringify([request.citations || [], request.source_flags || {}]);
      if (card.answerText !== request.answer_text || card.citationSignature !== citationSignature) {
        this.answer(card, request);
        card.answerText = request.answer_text;
      }
      card.stop.hidden = !unfinished.has(request.state);
      card.passport.hidden = !request.passport?.passed;
      if (card.citationSignature !== citationSignature) {
        card.citationSignature = citationSignature; card.quotes.replaceChildren();
        for (const citation of request.citations || []) {
          const flag = request.source_flags?.[citation.document_id];
          card.quotes.append(textElement('h4',`Цитата [${citation.number}]: ${this.documentName(citation.document_id,citation.name)} · Страница ${citation.page}${flag ? ` · ${flag === 'deleted' ? 'Источник удалён' : 'OCR исправлен; первоначальная цитата'}` : ''}`));
          const quote = textElement('blockquote',citation.quote);
          quote.className = 'cited-quote'; quote.id = `citation-${request.id}-${citation.number}`;
          card.quotes.append(quote);
        }
      }
      if (request.passport?.passed) {
        const signature = JSON.stringify([request.passport,request.source_flags || {}]);
        if (card.signature === signature) continue;
        card.signature = signature;
        card.contents.replaceChildren();
        card.contents.append(textElement('p',`Выбрано: ${request.passport.selected.map(id => this.documentName(id,request.passport.available.find(value => value.document_id === id)?.name)).join(', ')}`));
        card.contents.append(textElement('p',`Доступно для поиска: ${request.passport.available.map(value => this.documentName(value.document_id,value.name)).join(', ')}`));
        if (request.passport.excluded.length) card.contents.append(textElement('p',`Исключены как неготовые или недоступные: ${request.passport.excluded.map(id => this.documentName(id)).join(', ')}`));
        card.contents.append(textElement('p',`Найдено фрагментов: ${request.passport.found.length}. Передано модели: ${request.passport.passed.length}.`));
        if (request.passport.history_requests.length) card.contents.append(textElement('p',`Использована история: ${request.passport.history_requests.length} прежних ответов. Её источники: ${request.passport.history_dependencies.map(value => this.documentName(value.document_id)).join(', ')}`));
        for (const source of request.passport.available) for (const limitation of source.limitations)
          card.contents.append(textElement('p',`${this.documentName(source.document_id,source.name)}: ${limitation.message}`));
        if (request.passport.insufficient_evidence) card.contents.append(textElement('p', 'Недостаточно найденных оснований. Это не означает, что факта нет во всей библиотеке.'));
        for (const [index,fragment] of request.passport.passed.entries()) {
          card.contents.append(textElement('h4',`Фрагмент [${index+1}]: ${this.documentName(fragment.document_id,fragment.name)} · Страница ${fragment.page} · символы ${fragment.span_start}–${fragment.span_end}`));
          const item = textElement('blockquote', fragment.text); item.dataset.fragment = fragment.id;
          card.contents.append(item);
        }
      }
    }
    const latest = value.requests[value.requests.length-1];
    const signature = JSON.stringify([latest.passport || {},latest.state]);
    if (this.fragmentSignature !== signature || this.fragmentConversation !== this.selected) {
      this.fragmentSignature = signature; this.fragmentConversation = this.selected;
      $('early-fragments').replaceChildren();
      if (latest.passport?.passed) {
        $('early-fragments').append(textElement('h2', unfinished.has(latest.state) ? 'Найденные основания' : 'Сохранённые основания последнего вопроса'));
        if (!unfinished.has(latest.state)) $('early-fragments').append(textElement('p', `Состояние последнего вопроса: ${labels[latest.state] || latest.state}.`));
        for (const fragment of latest.passport.found) {
          const index = latest.passport.passed.findIndex(value => value.id === fragment.id);
          $('early-fragments').append(textElement('p',`${this.documentName(fragment.document_id,fragment.name)} · Страница ${fragment.page} · ${index>=0 ? 'Передан модели' : 'Не передан модели из-за объёма контекста'}`), textElement('blockquote', fragment.text));
        }
      }
    }
  }

  async submit() {
    if (!this.current() || !this.connected || this.sending.has(this.selected)) return;
    const identifier = this.selected;
    const draft = this.drafts.get(identifier);
    const pending = this.drafts.begin(identifier, {operation_key:crypto.randomUUID(), question:draft.text,
      document_ids:Array.from($('question-sources').querySelectorAll('input:checked'), input => input.value), tab_id:this.tab.id});
    this.sending.add(identifier); this.render();
    try {
      const request = await api(`/conversations/${identifier}/answers`, 'POST', pending.body, {'X-Tab-Proof':this.tab.proof});
      if (!this.current()) return;
      this.accepted(request, pending.body.question);
      if (this.selected === identifier) $('question').value = this.drafts.get(identifier).text;
    } catch (error) {
      if (!this.current()) return;
      if (['conversation_busy','no_ready_sources','invalid_scope','coordinator_unavailable','tab_disconnected','invalid_input','context_too_large','tokenizer_unavailable'].includes(error.message)) this.drafts.rejected(identifier, pending.body.operation_key);
      this.reportError(error);
    } finally {this.sending.delete(identifier); this.render();}
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
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    } catch (error) {if (this.current()) this.reportError(error);}
  }

  async receive(value) {
    if (!this.current()) return;
    if (value.kind === 'heartbeat') {
      await api(`/tabs/${this.tab.id}/heartbeat`, 'POST', undefined, {'X-Tab-Proof':this.tab.proof,
        'X-Connection-Epoch':String(value.payload.connection_epoch), 'X-Heartbeat-Challenge':value.payload.challenge});
      this.connected = true; this.render(); return;
    }
    if (this.cursor !== null && value.id <= this.cursor) return;
    if (value.kind === 'snapshot') {
      for (const history of value.payload.conversations) this.install(history);
      this.list(); this.render();
    } else {
      if (value.kind === 'accepted') {
        this.accepted({id:value.request_id, conversation_id:value.conversation_id,
          state:value.payload.state, version:value.payload.version, operation_key:value.payload.operation_key,
          scope:value.payload.scope, created_at:value.payload.created_at, answer_text:'', passport:{}}, value.payload.question);
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
      if (this.selected === value.conversation_id) this.render();
    }
    this.cursor = value.id;
  }
}
