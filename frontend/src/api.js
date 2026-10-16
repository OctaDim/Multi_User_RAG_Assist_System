import { token } from './auth.js';
export const origin = document.querySelector('meta[name="api-origin"]').content.replace(/\/$/, '');
export const reconnectMs = Number(document.querySelector('meta[name="reconnect-ms"]').content);
export const correctionRows = Number(document.querySelector('meta[name="correction-rows"]').content);
export const shortIdChars = Number(document.querySelector('meta[name="short-id-chars"]').content);

export async function publicSettings() {
  const response = await fetch(`${origin}/api/public-settings`, {cache:'no-store'});
  if (!response.ok) throw new Error('public_settings_unavailable');
  return response.json();
}

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
