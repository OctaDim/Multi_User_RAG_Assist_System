const credentialKey = 'rag:credential';
export function token() { return sessionStorage.getItem(credentialKey); }
export function signIn(value) {
  sessionStorage.clear();
  sessionStorage.setItem(credentialKey, value);
}
export function signOut() { sessionStorage.clear(); }
