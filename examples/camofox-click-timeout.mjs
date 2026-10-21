// Temporary carry for camofox-browser 1.18.1 (remove once upstream fixes /click).
// 1. The DOM-click fallback calls locator.evaluate() without a timeout. When a
//    re-render hides the target after the executor tagged it, that call waits
//    Playwright's 30 s default, the route's whole budget, and the server destroys
//    the tab (HTTP 410 tab_timeout). Bounded like the adjacent boundingBox() call,
//    the chain fails in time with its existing 422 and the tab survives.
// 2. When a click navigates to a slow page, Playwright reports "click action done"
//    and then times out waiting for the navigation. The route treated that as a
//    failed click and ran force, DOM and mouse fallbacks against a page that had
//    already gone, returning 422 after about 12 s for a click that worked. Now the
//    route waits (bounded, inside its budget) for that navigation to commit.
import { readFileSync, writeFileSync } from 'node:fs';

const file = process.argv[2] || '/app/server.js';
const patches = [
  ['DOM-click fallback',
    "          element.click();\n        });\n" +
    "        log('info', 'DOM click dispatched after Playwright click failure');",
    "          element.click();\n" +
    "        }, undefined, { timeout: Math.max(500, Math.min(3000, remainingBudget())) });\n" +
    "        log('info', 'DOM click dispatched after Playwright click failure');"],
  ['first click',
    "          await click({ timeout: 3000 });\n        } catch (err) {\n" +
    "          // Fallback 1: If intercepted by overlay, retry with force\n",
    "          await click({ timeout: 3000 });\n        } catch (err) {\n" +
    "          if (err.message.includes('click action done')) {\n" +
    "            const from = tabState.page.url();\n" +
    "            await tabState.page.waitForURL((url) => url.href !== from, { waitUntil: 'commit',\n" +
    "              timeout: Math.max(500, Math.min(10000, remainingBudget() - 5000)) }).catch(() => {});\n" +
    "            log('info', 'click delivered; waited for its navigation');\n" +
    "            return;\n" +
    "          }\n" +
    "          // Fallback 1: If intercepted by overlay, retry with force\n"],
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
