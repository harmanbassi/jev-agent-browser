// Temporary carry for camofox-browser 1.18.1 (remove once upstream bounds this call).
// The /click route's DOM-click fallback calls locator.evaluate() without a timeout.
// When a re-render hides the target after the executor tagged it, that call waits
// Playwright's 30 s default, the route's whole budget, and the server destroys the
// tab (HTTP 410 tab_timeout). Bounded like the adjacent boundingBox() call, the
// fallback chain fails in time with its existing 422, so the client observes again
// and the tab and its form state survive.
import { readFileSync, writeFileSync } from 'node:fs';

const file = process.argv[2] || '/app/server.js';
const before = "          element.click();\n        });\n" +
  "        log('info', 'DOM click dispatched after Playwright click failure');";
const after = "          element.click();\n" +
  "        }, undefined, { timeout: Math.max(500, Math.min(3000, remainingBudget())) });\n" +
  "        log('info', 'DOM click dispatched after Playwright click failure');";
const source = readFileSync(file, 'utf8');
if (source.split(before).length !== 2) {
  console.error(`${file}: DOM-click fallback not found exactly once; review this patch for the new base image`);
  process.exit(1);
}
writeFileSync(file, source.replace(before, after));
console.log('Bounded the /click DOM-click fallback');
