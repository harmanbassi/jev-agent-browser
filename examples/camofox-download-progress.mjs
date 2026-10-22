// Temporary carry for camofox-browser 1.18.1 (remove once upstream lists downloads early).
// A download is added to the tab's list only after saveAs() has received the whole
// file, so a large download stays invisible for as long as it takes, and a client
// that checks right after its click sees nothing and clicks again. List it as soon
// as the download event fires (state in_progress), and update that entry when it
// completes or fails. The per-tab cap holds from the start and never evicts a
// download still in progress; a file whose record was cleared meanwhile is deleted.
import { readFileSync, writeFileSync } from 'node:fs';

const file = process.argv[2] || '/app/lib/downloads.js';
const patches = [
  ['download trim',
    "async function trimTabDownloads(tabState) {\n" +
    "  while (tabState.downloads.length > MAX_DOWNLOAD_RECORDS_PER_TAB) {\n" +
    "    const stale = tabState.downloads.shift();\n" +
    "    await removeDownloadFileIfPresent(stale);\n  }\n}\n",
    "async function trimTabDownloads(tabState) {\n" +
    "  // Evict the oldest finished record, never one still in progress (its file has no\n" +
    "  // path yet). With every record in progress the list briefly exceeds the cap.\n" +
    "  while (tabState.downloads.length > MAX_DOWNLOAD_RECORDS_PER_TAB) {\n" +
    "    const index = tabState.downloads.findIndex((record) => record.state !== 'in_progress');\n" +
    "    if (index < 0) break;\n" +
    "    const [stale] = tabState.downloads.splice(index, 1);\n" +
    "    await removeDownloadFileIfPresent(stale);\n  }\n}\n"],
  ['download start',
    "    let failure = null;\n    let bytes = null;\n",
    "    const entry = { id: downloadId, tabId, url, suggestedFilename,\n" +
    "      mimeType: guessMimeTypeFromName(suggestedFilename) || guessMimeTypeFromName(url), bytes: null,\n" +
    "      createdAt: new Date().toISOString(), filePath: null, failure: null, state: 'in_progress' };\n" +
    "    tabState.downloads.push(entry);\n" +
    "    await trimTabDownloads(tabState);\n" +
    "    let failure = null;\n    let bytes = null;\n"],
  ['download completion',
    "    const mimeType = guessMimeTypeFromName(suggestedFilename) || guessMimeTypeFromName(url);\n" +
    "    tabState.downloads.push({\n" +
    "      id: downloadId,\n      tabId,\n      url,\n      suggestedFilename,\n      mimeType,\n      bytes,\n" +
    "      createdAt: new Date().toISOString(),\n      filePath: failure ? null : filePath,\n      failure,\n    });\n",
    "    const mimeType = entry.mimeType;\n" +
    "    Object.assign(entry, { bytes, filePath: failure ? null : filePath, failure,\n" +
    "      state: failure ? 'failed' : 'complete' });\n" +
    "    // Cleared (consumed or closed) while it was arriving: nothing lists the file, so delete it.\n" +
    "    if (!tabState.downloads.includes(entry)) await removeDownloadFileIfPresent(entry);\n"],
  ['download listing',
    "      failure: entry.failure,\n    };\n",
    "      failure: entry.failure,\n      state: entry.state || 'complete',\n    };\n"],
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
console.log('Downloads are listed when they start');
