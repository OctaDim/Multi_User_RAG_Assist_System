import {api, correctionRows} from './api.js';
import {token} from './auth.js';
import {textElement, messages, status, feedback, confirmAction} from './ui.js';
const $ = id => document.getElementById(id);
const labels = {receiving:'Загрузка',queued:'Ожидает обработки',processing:'Обрабатывается',awaiting_choice:'Нужен выбор режима',ready:'Готов',failed:'Обработка неуспешна',cancelled:'Отменён'};
const uncertain = error => ['request_timeout','network_error'].includes(error.message);
export class Documents {
  constructor({perform, onSources, inputPolicy, reveal}) {
    this.perform=perform; this.onSources=onSources; this.inputPolicy=inputPolicy; this.reveal=reveal;
    this.owner=null; this.ownerName=''; this.read=0; this.opening=0; this.urls=new Set(); this.editor=null;
    $('refresh-documents').onclick=()=>perform(()=>this.refresh(),$('refresh-documents'));
    $('own-library').onclick=()=>perform(()=>this.load(null),$('own-library'));
    $('close-editor').onclick=()=>this.closeEditor();
    $('document-editor').addEventListener('cancel',event=>{event.preventDefault();this.closeEditor();});
    window.addEventListener('beforeunload',event=>{if(this.dirty()){event.preventDefault();event.returnValue='';}});
    $('document-upload').onsubmit=event=>{event.preventDefault();perform(()=>this.upload(),event.submitter);};
    $('document-upload').elements.files.onchange=()=>{delete $('document-upload').dataset.uncertain;};
  }
  dirty() {return Boolean(this.editor?.dirty);}
  async allowLeave() {
    return !this.dirty() || await confirmAction('Несохранённые исправления','В документе есть несохранённый текст. Закрыть его и отказаться от исправлений?','Закрыть без сохранения');
  }
  releaseView() {
    ++this.opening;
    for(const url of this.urls) URL.revokeObjectURL(url);
    this.urls.clear(); this.editor=null; $('document-view').replaceChildren(); $('document-editor').close();
  }
  clear() {++this.read;this.owner=null;this.ownerName='';this.releaseView();$('library-status').textContent='';$('own-library').hidden=true;}
  async closeEditor() {if(await this.allowLeave())this.releaseView();}
  async load(owner=null,name='',reveal=true) {
    if(owner!==this.owner) {
      if(!await this.allowLeave())return;
      this.releaseView(); this.owner=owner;this.ownerName=name;
      $('documents').replaceChildren();
      $('library-title').textContent=owner?'Библиотека аккаунта':'Мои документы';
      $('library-context').textContent=owner?`${name||owner} · Только чтение`:'Материалы для поиска и ответов';
      $('document-upload').hidden=Boolean(owner);$('own-library').hidden=!owner;
    }
    if(reveal)this.reveal?.();
    await this.refresh();
    if(reveal&&owner===this.owner){$('library-title').tabIndex=-1;$('library-title').focus({preventScroll:true});}
  }
  async refresh() {
    const reading=++this.read, owner=this.owner, credential=token();
    $('library-status').textContent='Обновление документов…';
    let result;
    try {result=await api(owner?`/documents/admin/${owner}/library`:'/documents');}
    catch(error){if(reading===this.read) $('library-status').textContent=messages[error.message]||'Не удалось обновить документы. Повторите обновление.';throw error;}
    if(reading!==this.read||credential!==token()||owner!==this.owner)return;
    if(!result.readonly)this.onSources(result.documents);
    $('library-title').textContent=result.readonly?'Библиотека аккаунта':'Мои документы';
    $('library-context').textContent=result.readonly?`${this.ownerName||owner} · Только чтение`:'Материалы для поиска и ответов';
    $('document-upload').hidden=Boolean(result.readonly);$('own-library').hidden=!result.readonly;
    $('library-status').textContent=result.documents.length?`Документов: ${result.documents.length}`:'Пока нет документов. Загрузите первый файл, чтобы задавать вопросы.';
    const items=result.documents.map(file=>this.item(file,Boolean(result.readonly)));
    $('documents').replaceChildren(...items);
    const current=this.editor;
    if(current) {
      const file=result.documents.find(file=>file.id===current.file.id);
      if(!file){this.releaseView();return;}
      if(current.awaitingPublication) {
        if(file.state==='ready'&&file.published_revision!==current.revision)await this.open(file,current.readonly,true);
        else if(file.state==='failed') {
          current.awaitingPublication=false;current.dirty=true;current.form.inert=false;current.save.disabled=false;
          feedback(current.save,'Индексация исправлений не завершена. Ваш текст сохранён в редакторе.',true);
        }
      }
    }
  }
  item(file,readonly) {
    const item=document.createElement('li');item.dataset.document=file.id;
    item.append(textElement('strong',file.name),textElement('p',labels[file.state]||file.state));
    if(file.error)item.append(textElement('p',`${messages[file.error]||file.error}${file.failure_page?` · страница ${file.failure_page}`:''}`));
    const action=(label,run,style='secondary')=>{
      const button=textElement('button',label);button.type='button';button.className=style;
      button.onclick=()=>this.perform(()=>run(button),button);item.append(button);return button;
    };
    if(file.state==='failed') action('Открыть отчёт об обработке',()=>this.report(file));
    if(file.ready)action('Открыть документ',()=>this.open(file,readonly));
    if(!readonly&&file.state==='awaiting_choice') {
      item.append(textElement('p','OCR рукописей не разрешён. Выберите обработку только печатного текста или отмените документ.'));
      for(const [choice,label] of [['skip_handwriting','Загрузить только печатный текст'],['cancel','Отменить весь документ']])action(label,async()=>{await api(`/documents/${file.id}/mode`,'POST',{choice});await this.refresh();});
    }
    if(!readonly)action('Удалить документ',async()=>{
      const credential=token(),owner=this.owner;
      if(!await confirmAction('Удалить документ?',`«${file.name}» больше не будет доступен для поиска. Сохранённые ответы останутся с отметкой об удалённом источнике.`,'Удалить документ'))return;
      if(credential!==token()||owner!==this.owner)return;
      if(this.editor?.file.id===file.id&&this.dirty()&&!await this.allowLeave())return;
      await api(`/documents/${file.id}`,'DELETE');
      if(this.editor?.file.id===file.id)this.releaseView();
      await this.refresh();status('Документ удалён.');
    },'quiet');
    return item;
  }
  report(file) {
    const report=$('document-report');
    report.replaceChildren(textElement('h2','Отчёт об обработке документа'),textElement('p',`Файл: ${file.name}`),textElement('p',`Этап: ${['upload_failed','upload_incomplete','file_size_mismatch'].includes(file.error)?'загрузка документа':'обработка документа'}`),textElement('p',`Страница: ${file.failure_page||'не определена'}`),textElement('p',`Причина: ${messages[file.error]||file.error||'Не удалось обработать документ.'}`),textElement('p',file.ready?'Новая ревизия не опубликована; ранее готовая ревизия остаётся доступна.':'Документ целиком недоступен для поиска.'));
    if(file.mode==='skip_handwriting')report.append(textElement('p','Режим: только печатный текст; рукописные участки пропущены.'));
    const close=textElement('button','Закрыть отчёт');close.type='button';close.onclick=()=>report.close();report.append(close);report.showModal();
  }
  async open(file,readonly,published=false) {
    if(!published&&!await this.allowLeave())return;
    const opening=++this.opening,owner=this.owner,credential=token();
    const value=await api(`/documents/${file.id}`);
    if(opening!==this.opening||owner!==this.owner||credential!==token())return;
    this.releaseView();
    const generation=this.opening;
    const view=$('document-view');view.append(textElement('h3',file.name));
    const original=textElement('button','Скачать оригинал');original.type='button';original.className='secondary';
    original.onclick=()=>this.perform(async()=>{
      const blob=await api(`/documents/${file.id}/original`);
      if(generation!==this.opening)return;
      const url=URL.createObjectURL(blob);this.urls.add(url);
      const link=document.createElement('a');link.href=url;link.download=file.name;link.click();
    },original);
    const refresh=textElement('button','Проверить обработку');refresh.type='button';refresh.className='quiet';refresh.onclick=()=>this.perform(()=>this.refresh(),refresh);
    view.append(original,refresh,textElement('p',readonly?'Документ доступен только для чтения.': 'Проверьте распознанный текст по оригиналу. Изменения попадут в поиск после полной индексации.'));
    const form=document.createElement('form');form.id='document-correction';
    const initial=new Map();
    for(const page of value.pages) {
      const section=document.createElement('section');section.className='document-page';
      const label=textElement('label',file.format==='pdf'?`Страница ${page.page}: текст`:'Текст документа');
      const text=document.createElement('textarea');text.name=`page-${page.page}`;text.dataset.page=page.page;text.value=page.text;text.rows=correctionRows;text.readOnly=readonly;initial.set(page.page,page.text);
      label.append(text);section.append(label);form.append(section);
      if(file.format==='pdf') {
        const figure=document.createElement('figure');figure.className='original-page';
        const image=document.createElement('img');image.alt=`Оригинал страницы ${page.page}`;figure.append(image);section.prepend(figure);
        api(`/documents/${file.id}/pages/${page.page}/original`).then(blob=>{
          if(generation!==this.opening)return;
          const url=URL.createObjectURL(blob);this.urls.add(url);image.src=url;
          image.onload=()=>{
            for(const region of page.regions.filter(region=>region.kind==='skip'&&region.bbox)) {
              const marker=textElement('span','Пропуск');marker.className='skip-region';marker.title=region.text;
              const [x0,y0,x1,y1]=region.bbox;
              marker.style.left=`${x0/image.naturalWidth*100}%`;marker.style.top=`${y0/image.naturalHeight*100}%`;marker.style.width=`${(x1-x0)/image.naturalWidth*100}%`;marker.style.height=`${(y1-y0)/image.naturalHeight*100}%`;figure.append(marker);
            }
          };
        }).catch(error=>{
          if(generation!==this.opening)return;
          if(['unauthenticated','access_denied'].includes(error.message)) {this.perform(()=>{throw error;});return;}
          figure.append(textElement('p',messages[error.message]||'Не удалось загрузить страницу оригинала. Закройте документ и откройте снова.'));
        });
      }
    }
    const editor={file,readonly,revision:value.document.published_revision,form,initial,dirty:false,awaitingPublication:false};this.editor=editor;
    form.oninput=()=>{editor.dirty=Array.from(form.querySelectorAll('textarea')).some(input=>input.value!==initial.get(Number(input.dataset.page)));};
    if(!readonly) {
      const save=textElement('button','Сохранить исправления');editor.save=save;form.append(save);
      if(['queued','processing'].includes(value.document.state)){save.disabled=true;form.querySelectorAll('textarea').forEach(input=>{input.readOnly=true;});form.append(textElement('p','Новая ревизия обрабатывается. Для проверки нажмите «Проверить обработку».'));}
      form.onsubmit=event=>{event.preventDefault();if(editor.awaitingPublication)return;this.perform(async()=>{
        const pages=Array.from(form.querySelectorAll('textarea'),input=>({page:Number(input.dataset.page),text:input.value}));
        form.inert=true;
        try {
          await api(`/documents/${file.id}/corrections`,'POST',{base_revision:editor.revision,pages});
          if(this.editor!==editor)return;
          editor.awaitingPublication=true;editor.dirty=false;
          status('Исправления приняты. Новая ревизия появится после полной индексации.');
          feedback(save,'Исправления приняты. Ожидается публикация новой ревизии.');
        } finally {if(this.editor===editor&&!editor.awaitingPublication)form.inert=false;}
      },save).then(()=>{if(this.editor===editor&&editor.awaitingPublication)save.disabled=true;});};
      if(file.format==='pdf') {
        const complete=textElement('button','Обработать PDF полностью');complete.type='button';complete.className='secondary';complete.disabled=['queued','processing'].includes(file.state);
        complete.onclick=()=>this.perform(async()=>{
          if(!await this.allowLeave())return;
          await api(`/documents/${file.id}/mode`,'POST',{choice:'complete'});this.releaseView();await this.refresh();
        },complete);view.append(complete);
      }
    }
    view.append(form);$('document-editor').showModal();
  }
  async upload() {
    const form=$('document-upload');
    if(form.dataset.uncertain){feedback(form.querySelector('button'),'Предыдущая загрузка могла быть принята. Проверьте список и выберите файлы заново перед новой загрузкой.',true);return;}
    const files=Array.from(form.elements.files.files);
    if(files.some(file=>Array.from(file.name).length>this.inputPolicy().filename_max))throw new Error('filename_too_long');
    try {
      const batch=await api('/documents/uploads','POST',{files:files.map(file=>({name:file.name,size:file.size}))});
      for(let i=0;i<batch.documents.length;i++)await api(`/documents/${batch.documents[i].id}/original`,'PUT',files[i]);
      form.reset();status('Файлы приняты. Обработка выполняется в фоне.');await this.refresh();
    } catch(error) {
      if(uncertain(error))form.dataset.uncertain='true';
      await this.refresh().catch(()=>{});throw error;
    }
  }
}
