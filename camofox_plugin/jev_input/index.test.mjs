// node --test camofox_plugin/jev_input/index.test.mjs   (run by tests/test_camofox_plugin.py)
import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { jevClick, navigationStarted, register } from './index.js';

function fixture({ navigatesOnUp = false } = {}) {
  const calls = [];
  const page = new EventEmitter();
  const mainFrame = {};
  page.mainFrame = () => mainFrame;
  page.waitForLoadState = async (state) => calls.push(['load', state]);
  page.waitForEvent = (event, { predicate }) => new Promise((resolve, reject) => {
    const onNav = (frame) => { if (predicate(frame)) { page.off(event, onNav); calls.push(['commit']); resolve(frame); } };
    page.on(event, onNav);
    setTimeout(() => { page.off(event, onNav); reject(new Error('timeout')); }, 50);
  });
  page.mouse = {
    move: async (x, y) => calls.push(['move', x, y]),
    down: async () => calls.push(['down']),
    up: async () => {
      calls.push(['up']);
      if (navigatesOnUp) {
        page.emit('request', { isNavigationRequest: () => true, frame: () => mainFrame });
        setTimeout(() => page.emit('framenavigated', mainFrame), 10); // the new document commits later
      }
    },
  };
  const tab = { page, lastSnapshot: 'stale' };
  const session = { tabGroups: new Map([['g', new Map([['t1', tab]])]]), lastAccess: 0 };
  const ctx = {
    sessions: new Map([['u1', session]]),
    normalizeUserId: (u) => u,
    log: () => {},
    safeError: (e) => e.message,
  };
  return { calls, tab, session, ctx, page };
}

function call(handler, params, body) {
  return new Promise((resolve) => {
    const res = {
      code: 200,
      status(c) { this.code = c; return this; },
      json(b) { resolve({ code: this.code, body: b }); },
    };
    handler({ params, body }, res);
  });
}

test('clicks at the coordinates with real mouse events and clears the snapshot', async () => {
  const f = fixture();
  const out = await call(jevClick(f.ctx), { tabId: 't1' }, { userId: 'u1', x: 10.5, y: 20 });
  assert.deepEqual(out, { code: 200, body: { ok: true, navigated: false } });
  assert.deepEqual(f.calls, [['move', 10.5, 20], ['down'], ['up']]);
  assert.equal(f.tab.lastSnapshot, null);
  assert.ok(f.session.lastAccess > 0);
});

test('a click that navigates waits for the new document to commit, then load', async () => {
  const f = fixture({ navigatesOnUp: true });
  const out = await call(jevClick(f.ctx), { tabId: 't1' }, { userId: 'u1', x: 1, y: 2 });
  assert.deepEqual(out.body, { ok: true, navigated: true });
  assert.deepEqual(f.calls.slice(-2), [['commit'], ['load', 'domcontentloaded']]);
});

test('a navigation that never commits still returns (and does not wait for load)', async () => {
  const f = fixture();
  f.page.mouse.up = async () => {
    f.calls.push(['up']);
    f.page.emit('request', { isNavigationRequest: () => true, frame: () => f.page.mainFrame() });
  };
  const out = await call(jevClick(f.ctx), { tabId: 't1' }, { userId: 'u1', x: 1, y: 2 });
  assert.deepEqual(out.body, { ok: true, navigated: true });
  assert.ok(!f.calls.some((c) => c[0] === 'load'));
});

test('sub-frame and non-navigation requests do not count as navigating', async () => {
  const page = new EventEmitter();
  const main = {};
  page.mainFrame = () => main;
  const started = navigationStarted(page, 30);
  page.emit('request', { isNavigationRequest: () => false, frame: () => main });
  page.emit('request', { isNavigationRequest: () => true, frame: () => ({}) });
  assert.equal(await started, false);
  assert.equal(page.listenerCount('request'), 0, 'listener removed');
});

test('rejects missing or non-numeric coordinates', async () => {
  const f = fixture();
  for (const body of [{ userId: 'u1', x: 1 }, { userId: 'u1', x: 'a', y: 2 }, { x: 1, y: 2 }]) {
    assert.equal((await call(jevClick(f.ctx), { tabId: 't1' }, body)).code, 400);
  }
  assert.deepEqual(f.calls, []);
});

test('unknown tab or user is a 404', async () => {
  const f = fixture();
  assert.equal((await call(jevClick(f.ctx), { tabId: 'nope' }, { userId: 'u1', x: 1, y: 1 })).code, 404);
  assert.equal((await call(jevClick(f.ctx), { tabId: 't1' }, { userId: 'u9', x: 1, y: 1 })).code, 404);
});

test('a mouse failure is a 409 the client treats as a changed page', async () => {
  const f = fixture();
  f.page.mouse.down = async () => { throw new Error('Target closed'); };
  const out = await call(jevClick(f.ctx), { tabId: 't1' }, { userId: 'u1', x: 1, y: 1 });
  assert.deepEqual(out, { code: 409, body: { error: 'Target closed' } });
});

test('register mounts the route', async () => {
  const routes = [];
  await register({ post: (p, h) => routes.push([p, typeof h]) }, fixture().ctx);
  assert.deepEqual(routes, [['/tabs/:tabId/jev-click', 'function']]);
});
