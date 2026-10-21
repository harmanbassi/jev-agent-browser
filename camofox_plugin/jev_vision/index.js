/** Masked in-memory observations for jev-browser. No caller-supplied scripts/selectors. */
import { readFileSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';

const snapshot = readFileSync(new URL('./snapshot.js', import.meta.url), 'utf8');
export const snapshotHash = createHash('sha256').update(snapshot).digest('hex');
export const MASK = 'input,textarea,select,[contenteditable]:not([contenteditable="false"]),iframe,object,embed,[data-jev-private]';
const busy = new WeakSet();
const same = (a, b) => JSON.stringify([a.marker, a.actions, a.w, a.h]) === JSON.stringify([b.marker, b.actions, b.w, b.h]);

// Runs in the same isolated evaluation realm as snapshot.js. Opaque embeds and
// explicitly private regions cannot contribute either text or model targets.
export const SAFE_STATE = `(() => {
  const s = ${snapshot};
  if (!s) return null;
  const hidden = 'iframe,object,embed,[data-jev-private]';
  const masked = ${JSON.stringify(MASK)};
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange(), words = [];
  let n, length = 0;
  while ((n = walker.nextNode()) && length < 6000) {
    const p = n.parentElement, text = n.textContent.trim();
    if (!p || !text || p.closest(masked + ',script,style,noscript,template,[aria-hidden="true"],[inert]') ||
        !p.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) continue;
    range.selectNodeContents(n); const r = range.getBoundingClientRect();
    if (r.width && r.height && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth) {
      words.push(text); length += text.length;
    }
  }
  const actions = s.actions.filter(a => {
    const e = window.__jevFast.nodes.get(a.node);
    return !e || !e.closest(hidden);
  }).map(a => {
    const e = window.__jevFast.nodes.get(a.node);
    if (!e || !e.matches(masked) || a.kind === 'select') return a;
    // Values remain available only to the local executor, never the image model.
    return {...a, value:'', current_value:'', label:e.getAttribute('aria-label') ||
      [...(e.labels || [])].map(l => l.innerText).join(' ') || a.role};
  });
  return {url:s.url, title:s.title, text:words.join('\\n'), actions};
})()`;

export function observation(ctx) {
  return async (req, res) => {
    const { userId, expectedUrl, snapshotHash: expectedHash } = req.body || {};
    if (typeof userId !== 'string' || !userId || typeof expectedUrl !== 'string' ||
        !/^https?:\/\//.test(expectedUrl) || expectedHash !== snapshotHash) {
      return res.status(400).json({ error: 'invalid observation request or snapshot version' });
    }
    const session = ctx.sessions.get(ctx.normalizeUserId(userId));
    let tab;
    if (session) for (const group of session.tabGroups.values()) {
      if (group.has(req.params.tabId)) tab = group.get(req.params.tabId);
    }
    if (!tab) return res.status(404).json({ error: 'tab not found' });
    if (busy.has(tab)) return res.status(409).json({ error: 'observation busy' });
    busy.add(tab);
    try {
      const { page } = tab;
      const before = await page.evaluate(snapshot);
      if (!before || before.url !== expectedUrl) return res.status(409).json({ error: 'page changed' });
      session.lastAccess = Date.now();
      const image = await page.screenshot({ type:'png', fullPage:false, scale:'css',
        mask:[page.locator(MASK)], maskColor:'#000000', caret:'hide', timeout:5000 });
      const safe = await page.evaluate(SAFE_STATE);
      const after = await page.evaluate(snapshot);
      if (!after || !safe || after.url !== expectedUrl || !same(before, after) || safe.url !== after.url) {
        return res.status(409).json({ error: 'page changed during observation' });
      }
      if (image.length > 8 * 1024 * 1024) return res.status(413).json({ error:'observation too large' });
      res.set('Cache-Control', 'no-store');
      res.json({ protocol:1, snapshotHash, captureId:randomUUID(), capturedAt:Date.now(),
        masked:true, snapshot:after, safe, image:{format:'png', data:image.toString('base64')} });
    } catch {
      // Never forward page contents, image data or underlying exception details.
      res.status(503).json({ error:'masked observation unavailable' });
    } finally {
      busy.delete(tab);
    }
  };
}

export function register(app, ctx) {
  app.get('/jev/vision', ctx.auth(), (_req, res) => res.json({protocol:1, snapshotHash, masked:true}));
  app.post('/tabs/:tabId/jev-observation', ctx.auth(), observation(ctx));
  ctx.log('info', 'jev_vision plugin registered', {protocol:1});
}
