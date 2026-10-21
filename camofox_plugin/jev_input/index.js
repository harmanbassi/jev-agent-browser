/**
 * jev_input: a lean pointer click for jev-browser.
 *
 *   POST /tabs/:tabId/jev-click  { userId, x, y }
 *
 * Real Playwright mouse events (move, down, up) at viewport coordinates, and
 * nothing else. The core /click route adds an actionability wait, a fixed
 * 500 ms settle and a full accessibility-ref rebuild after every click (~2 s on
 * Google Flights) for the browser_* tools' element refs, which jev-browser
 * never uses: it hit-tests the target itself (elementFromPoint) immediately
 * before calling, and runs its own settle wait and snapshot after.
 *
 * One wait is kept, and made conditional: if the click starts a main-frame
 * navigation within NAV_START_MS, return only once the NEW document has
 * committed (framenavigated) and loaded its DOM. waitForLoadState alone is not
 * enough: the old document is already loaded, so it returns at once while the
 * old page is still showing (measured: navigated=true, yet location stayed on
 * Wikipedia's main page for ~1.5 s, and Jev declared a false "done").
 *
 * Install: mount this directory at /app/plugins/jev_input and list
 * "jev_input" in camofox.config.json's plugins.
 */

export const NAV_START_MS = 150;
export const NAV_LOAD_MS = 5000;

// Resolves true if the click starts a main-frame navigation within NAV_START_MS.
export function navigationStarted(page, ms = NAV_START_MS) {
  return new Promise((resolve) => {
    const onRequest = (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) done(true);
    };
    const timer = setTimeout(() => done(false), ms);
    function done(started) {
      clearTimeout(timer);
      page.off('request', onRequest);
      resolve(started);
    }
    page.on('request', onRequest);
  });
}

// Mirrors server.js findTab (not exposed on the plugin ctx).
export function findTab(session, tabId) {
  for (const group of session.tabGroups.values()) {
    if (group.has(tabId)) return group.get(tabId);
  }
  return null;
}

export function jevClick(ctx) {
  return async (req, res) => {
    const { userId, x, y } = req.body || {};
    if (!userId || !Number.isFinite(x) || !Number.isFinite(y)) {
      return res.status(400).json({ error: 'userId, x and y are required' });
    }
    const session = ctx.sessions.get(ctx.normalizeUserId(userId));
    const tabState = session && findTab(session, req.params.tabId);
    if (!tabState) return res.status(404).json({ error: 'tab not found' });
    session.lastAccess = Date.now();
    // ponytail: no per-tab lock (withTabLock is not on ctx); jev-browser drives
    // one tab sequentially. Add a lock if concurrent callers ever share a tab.
    try {
      const { page } = tabState;
      await page.mouse.move(x, y);
      await page.mouse.down();
      const navigating = navigationStarted(page); // listen before the click lands
      // Subscribed before the click so a fast commit cannot slip past; resolves
      // false on timeout rather than rejecting, since most clicks never navigate.
      const committed = page.waitForEvent('framenavigated', {
        predicate: (frame) => frame === page.mainFrame(), timeout: NAV_LOAD_MS,
      }).then(() => true, () => false);
      await page.mouse.up();
      const navigated = await navigating;
      if (navigated) {
        // Still loading after NAV_LOAD_MS is not a click failure: jev-browser re-observes
        // until the page settles, so log it and return.
        try {
          if (!(await committed)) throw new Error(`no main-frame commit within ${NAV_LOAD_MS} ms`);
          await page.waitForLoadState('domcontentloaded', { timeout: NAV_LOAD_MS });
        } catch (err) {
          ctx.log('info', 'jev-click: new document still loading', { tabId: req.params.tabId, error: err.message });
        }
      }
      tabState.lastSnapshot = null; // browser_* tools rebuild refs on their next snapshot
      res.json({ ok: true, navigated });
    } catch (err) {
      ctx.log('warn', 'jev-click failed', { tabId: req.params.tabId, error: err.message });
      res.status(409).json({ error: ctx.safeError(err) });
    }
  };
}

export async function register(app, ctx) {
  app.post('/tabs/:tabId/jev-click', jevClick(ctx));
  ctx.log('info', 'jev_input plugin registered', { route: 'POST /tabs/:tabId/jev-click' });
}
