import { token } from './auth.js';
export const origin = document.querySelector('meta[name="api-origin"]').content.replace(/\/$/, '');

export async function api(path, method = 'GET', body, extraHeaders = {}) {
  const credential = token();
  const headers = {...extraHeaders};
  const binary = body instanceof Blob;
  if (credential) headers.Authorization = `Bearer ${credential}`;
  if (body !== undefined) headers['Content-Type'] = binary ? 'application/octet-stream' : 'application/json';
  const response = await fetch(`${origin}/api${path}`, {
    method, headers, body: body === undefined ? undefined : binary ? body : JSON.stringify(body),
  });
  const result = response.headers.get('content-type')?.includes('application/json') ? await response.json() : await response.blob();
  if (token() !== credential) throw new Error('session_changed');
  if (!response.ok) throw new Error(result?.error || 'request_failed');
  return result;
}
