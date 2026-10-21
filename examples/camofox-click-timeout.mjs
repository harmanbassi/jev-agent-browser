// Temporary carry for camofox-browser 1.18.1 (remove once upstream fixes /click).
// 1. The DOM-click fallback calls locator.evaluate() without a timeout. When a
//    re-render hides the target after the executor tagged it, that call waits
//    Playwright's 30 s default, the route's whole budget, and the server destroys
//    the tab (HTTP 410 tab_timeout). Bounded like the adjacent boundingBox() call,
//    the chain fails in time with its existing 422 and the tab survives.
// 2. When a click navigates to a slow page, Playwright reports "click action done"
//    and then times out waiting for the navigation. The route treated that as a
//    failed click and ran force, DOM and mouse fallbacks against a page that had
//    already gone (a second activation), returning 422 after about 12 s for a
//    click that worked. Every attempt goes through the route's click wrapper (the
//    first click, forced retries and the search-results path), so the wrapper now
//    treats a delivered click as success and waits, bounded inside the route
//    budget, for its navigation to commit.
import { readFileSync, writeFileSync } from 'node:fs';

const file = process.argv[2] || '/app/server.js';
const patches = [
  ['DOM-click fallback',
    "          element.click();\n        });\n" +
    "        log('info', 'DOM click dispatched after Playwright click failure');",
    "          element.click();\n" +
    "        }, undefined, { timeout: Math.max(500, Math.min(3000, remainingBudget())) });\n" +
    "        log('info', 'DOM click dispatched after Playwright click failure');"],
  ['click wrapper',
    "        const click = async (options) => clickWithDownloadGuard(tabState, () => locator.click(options));\n",
    "        const click = async (options) => clickWithDownloadGuard(tabState, async () => {\n" +
    "          try {\n" +
    "            return await locator.click(options);\n" +
    "          } catch (err) {\n" +
    "            if (!String(err?.message).includes('click action done')) throw err;\n" +
    "            const from = tabState.page.url();\n" +
    "            await tabState.page.waitForURL((url) => url.href !== from, { waitUntil: 'commit',\n" +
    "              timeout: Math.max(500, Math.min(10000, remainingBudget() - 5000)) }).catch(() => {});\n" +
    "            log('info', 'click delivered; waited for its navigation');\n" +
    "          }\n" +
    "        });\n"],
];
let source = readFileSync(file, 'utf8');
for (const [name, before, after] of patches) {
  if (source.split(before).length !== 2) {
    console.error(`${file}: ${name} not found exactly once; review this patch for the new base image`);
    process.exit(1);
  }
  source = source.replace(before, after);
}
writeFileSync(file, source);
console.log('Patched the /click fallbacks');
