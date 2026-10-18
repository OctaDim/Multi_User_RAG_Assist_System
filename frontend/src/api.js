import { token } from './auth.js';
export const origin = document.querySelector('meta[name="api-origin"]').content.replace(/\/$/, '');
export const reconnectMs = Number(document.querySelector('meta[name="reconnect-ms"]').content);
export const correctionRows = Number(document.querySelector('meta[name="correction-rows"]').content);
export const shortIdChars = Number(document.querySelector('meta[name="short-id-chars"]').content);
const requestTimeoutMs = Number(document.querySelector('meta[name="request-timeout-ms"]').content);
async function request(path, options) {
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), requestTimeoutMs);
  try {
    const response = await fetch(`${origin}/api${path}`, {...options, signal:abort.signal});
    const result = response.headers.get('content-type')?.includes('application/json') ? await response.json() : await response.blob();
    if (!response.ok) throw new Error(result?.error || 'request_failed');
    return result;
  } catch (error) {
    if (abort.signal.aborted) throw new Error('request_timeout');
    if (error instanceof TypeError) throw new Error('network_error');
    throw error;
  } finally {clearTimeout(timeout);}
}
export async function publicSettings() {return request('/public-settings', {cache:'no-store'});}
export async function api(path, method = 'GET', body, extraHeaders = {}) {
  const credential = token();
  const headers = {...extraHeaders};
  const binary = body instanceof Blob;
  if (credential) headers.Authorization = `Bearer ${credential}`;
  if (body !== undefined) headers['Content-Type'] = binary ? 'application/octet-stream' : 'application/json';
  try {
    return await request(path, {method, headers, body:body === undefined ? undefined : binary ? body : JSON.stringify(body)});
  } finally {
    if (token() !== credential) throw new Error('session_changed');
  }
}
