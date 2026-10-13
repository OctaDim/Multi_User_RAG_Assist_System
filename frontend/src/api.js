import { token } from './auth.js';
const origin = document.querySelector('meta[name="api-origin"]').content.replace(/\/$/, '');

export async function api(path, method = 'GET', body) {
  const headers = {};
  if (token()) headers.Authorization = `Bearer ${token()}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`${origin}/api${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'request_failed');
  return result;
}
