const prefix = 'rag:draft:';
export const tabKey = 'rag:tab';

export function clearDrafts() {
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith(prefix) || key === tabKey || key === 'rag:conversation' || key === 'rag:owner') sessionStorage.removeItem(key);
  }
}

// A reopened tab can carry sessionStorage; only reload keeps its drafts and identity.
if (performance.getEntriesByType('navigation')[0]?.type !== 'reload') clearDrafts();

export class Drafts {
  constructor(owner) {
    if (sessionStorage.getItem('rag:owner') !== owner) clearDrafts();
    sessionStorage.setItem('rag:owner', owner);
    this.owner = owner;
  }

  key(conversation) { return `${prefix}${this.owner}:${conversation}`; }
  get(conversation) {
    return JSON.parse(sessionStorage.getItem(this.key(conversation)) || 'null') || {text:'', revision:0, pending:null};
  }
  save(conversation, value) { sessionStorage.setItem(this.key(conversation), JSON.stringify(value)); }
  edit(conversation, text) {
    const value = this.get(conversation);
    this.save(conversation, {...value, text, revision:value.revision+1});
  }
  begin(conversation, body) {
    const value = this.get(conversation);
    if (value.pending) return value.pending;
    const pending = {revision:value.revision, body};
    this.save(conversation, {...value, pending});
    return pending;
  }
  accepted(conversation, operationKey) {
    const value = this.get(conversation);
    if (value.pending?.body.operation_key !== operationKey) return;
    const sameRevision = value.revision === value.pending.revision;
    this.save(conversation, {...value, text:sameRevision ? '' : value.text,
      revision:value.revision+Number(sameRevision), pending:null});
  }
  rejected(conversation, operationKey) {
    const value = this.get(conversation);
    if (value.pending?.body.operation_key === operationKey) this.save(conversation, {...value, pending:null});
  }
}
