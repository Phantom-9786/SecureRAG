import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Exercise the API boundary without adding a browser or test-framework dependency.
const source = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { api, allPages, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`);
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test('cookie-authenticated mutations preserve the CSRF contract', async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/v1/conversations');
    assert.equal(init.credentials, 'same-origin');
    assert.equal(init.cache, 'no-store');
    assert.equal(init.headers['X-CSRF-Token'], 'test-csrf');
    assert.deepEqual(JSON.parse(init.body), { title: 'Example' });
    return Response.json({ id: 'saved' }, { status: 201 });
  };
  assert.deepEqual(await api('/conversations', { method: 'POST', body: { title: 'Example' }, csrf: 'test-csrf' }), { id: 'saved' });
});
test('capacity errors retain retry guidance and never automatically resubmit', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({ detail: 'busy' }, { status: 429, headers: { 'Retry-After': '17' } }); };
  await assert.rejects(api('/conversations/test/messages', { method: 'POST', body: {} }), error => error instanceof ApiError && error.status === 429 && error.message.includes('17 seconds'));
  assert.equal(calls, 1);
});
test('a proxy HTML error produces safe recovery instructions', async () => {
  globalThis.fetch = async () => new Response('<html>internal proxy data</html>', { status: 502 });
  await assert.rejects(api('/conversations/test/messages'), error => error.status === 502 && error.message.includes('Refresh the current view') && !error.message.includes('internal proxy data'));
});
test('unauthorized responses retain their status for session clearing', async () => {
  globalThis.fetch = async () => Response.json({ detail: 'Not authenticated' }, { status: 401 });
  await assert.rejects(api('/auth/me'), error => error instanceof ApiError && error.status === 401);
});
test('logout accepts an empty 204 response', async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await api('/auth/logout', { method: 'POST', csrf: 'test' }), undefined);
});
test('pagination includes conversations beyond the first hundred', async () => {
  const urls = [];
  globalThis.fetch = async url => { urls.push(url); return Response.json(url.includes('offset=0&') ? Array.from({ length: 100 }, (_, id) => ({ id })) : [{ id: 100 }]); };
  const result = await allPages('/conversations');
  assert.equal(result.length, 101);
  assert.equal(result[100].id, 100);
  assert.deepEqual(urls, ['/api/v1/conversations?offset=0&limit=100', '/api/v1/conversations?offset=100&limit=100']);
});
test('cancelled reads stay cancellations instead of showing a server error', async () => {
  globalThis.fetch = async () => { throw new DOMException('Cancelled', 'AbortError'); };
  await assert.rejects(api('/auth/me'), error => error.name === 'AbortError' && !(error instanceof ApiError));
});

test('multipart upload leaves Content-Type to the browser and includes CSRF', async () => {
  const form = new FormData();
  form.append('title', 'Example document');
  form.append('category_id', 'category-1');
  form.append('file', new Blob(['%PDF-test'], { type: 'application/pdf' }), 'example.pdf');
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/v1/admin/documents');
    assert.equal(init.body, form);
    assert.equal(init.headers['Content-Type'], undefined);
    assert.equal(init.headers['X-CSRF-Token'], 'test-csrf');
    assert.equal(init.credentials, 'same-origin');
    return Response.json({ id: 'document-1' }, { status: 201 });
  };
  assert.deepEqual(await api('/admin/documents', { method: 'POST', csrf: 'test-csrf', form }), { id: 'document-1' });
});

test('edge authentication throttling is distinct from Gemini capacity', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response('rate limited', { status: 429 }); };
  await assert.rejects(api('/auth/login', { method: 'POST', body: {} }), error => error.status === 429 && error.message.includes('sign-in attempts') && !error.message.includes('AI capacity'));
  assert.equal(calls, 1);
});
