"""Runs the Camofox jev_input plugin's own node tests (camofox_plugin/jev_input)."""
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "camofox_plugin/jev_input"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("name", ["jev_input", "jev_vision"])
def test_jev_input_plugin_node_suite(name, tmp_path):
    plugin = PLUGIN.parent / name
    if name == "jev_vision":
        # The image installs the shared snapshot beside the capture plugin.
        shutil.copytree(plugin, tmp_path / name)
        plugin = tmp_path / name
        shutil.copy2(PLUGIN.parents[1] / "jev_browser/snapshot.js", plugin / "snapshot.js")
    out = subprocess.run(["node", "--test", str(plugin / "index.test.mjs")], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "# fail 0" in out.stdout


CLICK_FALLBACK = """      const dispatchDomClick = async (locator) => {
        await locator.evaluate((element) => {
          if (!(element instanceof HTMLElement)) throw new Error('Element is not an HTMLElement');
          element.click();
        });
        log('info', 'DOM click dispatched after Playwright click failure');
      };
"""
CLICK_WRAPPER = """        const click = async (options) => clickWithDownloadGuard(tabState, () => locator.click(options));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_image_bounds_the_dom_click_fallback_or_fails_the_build(tmp_path):
    patch = PLUGIN.parents[1] / "examples/camofox-click-timeout.mjs"
    server = tmp_path / "server.js"
    server.write_text("const before = 1;\n" + CLICK_FALLBACK + CLICK_WRAPPER)
    out = subprocess.run(["node", str(patch), str(server)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    patched = server.read_text()
    assert "}, undefined, { timeout: Math.max(500, Math.min(3000, remainingBudget())) });" in patched
    # Every click attempt (first, forced, search-results) goes through this wrapper: one that
    # Playwright delivered while its navigation is still loading is a success, never a reason
    # to activate the departed page again through the fallbacks.
    wrapper = patched[patched.index("const click = async (options)"):]
    assert "includes('click action done')" in wrapper and "waitForURL" in wrapper
    assert patched.count("click action done") == 1
    # An attempt that never reached the page, whose target is gone, is reported as such
    # instead of feeding the fallbacks a replaced element.
    assert "includes('performing click action')" in wrapper and "code: 'target_replaced'" in wrapper
    assert "statusCode: 409" in wrapper
    for changed in (patched, CLICK_FALLBACK * 2 + CLICK_WRAPPER, CLICK_FALLBACK, CLICK_WRAPPER, "unrelated"):
        server.write_text(changed)
        out = subprocess.run(["node", str(patch), str(server)], capture_output=True, text=True)
        assert out.returncode != 0 and "not found exactly once" in out.stderr


def test_dockerfile_applies_the_click_patch_and_the_build_context_includes_it():
    repo = PLUGIN.parents[1]
    dockerfile = (repo / "examples/Dockerfile").read_text()
    assert "ARG CAMOFOX_CLICK_PATCH=1" in dockerfile.split("FROM ", 1)[1]  # in scope after FROM
    assert 'if [ "$CAMOFOX_CLICK_PATCH" = "1" ]; then node /tmp/camofox-click-timeout.mjs /app/server.js; fi' in dockerfile
    assert "CAMOFOX_CLICK_PATCH=0" in (repo / "docs/camofox-operations.md").read_text()
    assert "!examples/camofox-click-timeout.mjs" in (repo / ".dockerignore").read_text().splitlines()


DOWNLOAD_LISTENER = """    let failure = null;
    let bytes = null;

    try {
      await download.saveAs(filePath);
    } catch (err) {
      failure = String(err?.message || err || 'download_save_failed');
    }

    const mimeType = guessMimeTypeFromName(suggestedFilename) || guessMimeTypeFromName(url);
    tabState.downloads.push({
      id: downloadId,
      tabId,
      url,
      suggestedFilename,
      mimeType,
      bytes,
      createdAt: new Date().toISOString(),
      filePath: failure ? null : filePath,
      failure,
    });
"""
DOWNLOAD_TRIM = """async function trimTabDownloads(tabState) {
  while (tabState.downloads.length > MAX_DOWNLOAD_RECORDS_PER_TAB) {
    const stale = tabState.downloads.shift();
    await removeDownloadFileIfPresent(stale);
  }
}
"""
DOWNLOAD_LIST = """    const item = {
      id: entry.id,
      failure: entry.failure,
    };
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_image_lists_a_download_as_soon_as_it_starts_or_fails_the_build(tmp_path):
    patch = PLUGIN.parents[1] / "examples/camofox-download-progress.mjs"
    downloads = tmp_path / "downloads.js"
    downloads.write_text(DOWNLOAD_TRIM + DOWNLOAD_LISTENER + DOWNLOAD_LIST)
    out = subprocess.run(["node", str(patch), str(downloads)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    patched = downloads.read_text()
    # Listed with state in_progress before saveAs waits for the whole file, then updated in place.
    assert patched.index("state: 'in_progress'") < patched.index("await download.saveAs")
    assert "state: failure ? 'failed' : 'complete'" in patched and "tabState.downloads.push({\n" not in patched
    assert "state: entry.state || 'complete'," in patched
    # The cap holds from the moment a download starts; a file whose entry is gone is deleted.
    start = patched.index("tabState.downloads.push(entry);")
    assert patched.index("await trimTabDownloads(tabState);", start) < patched.index("await download.saveAs")
    assert "if (!tabState.downloads.includes(entry)) await removeDownloadFileIfPresent(entry);" in patched
    # Run the patched trim: it evicts the oldest finished record, never one still in progress.
    trim = patched[patched.index("async function trimTabDownloads"):patched.index("\n}\n", patched.index("async function trimTabDownloads")) + 3]
    script = ("const MAX_DOWNLOAD_RECORDS_PER_TAB = 2; const removed = [];"
              "async function removeDownloadFileIfPresent(r) { removed.push(r.id); }" + trim +
              "const tab = {downloads: [{id: 'a', state: 'in_progress'}, {id: 'b', state: 'complete'},"
              " {id: 'c', state: 'complete'}]};"
              "trimTabDownloads(tab).then(() => console.log(JSON.stringify([tab.downloads.map(d => d.id), removed])));")
    ran = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert ran.stdout.strip() == '[["a","c"],["b"]]', ran.stdout + ran.stderr
    for changed in (patched, DOWNLOAD_TRIM + DOWNLOAD_LISTENER, DOWNLOAD_LISTENER + DOWNLOAD_LIST, "unrelated"):
        downloads.write_text(changed)
        out = subprocess.run(["node", str(patch), str(downloads)], capture_output=True, text=True)
        assert out.returncode != 0 and "not found exactly once" in out.stderr


def test_dockerfile_applies_the_download_patch_behind_its_own_build_arg():
    repo = PLUGIN.parents[1]
    dockerfile = (repo / "examples/Dockerfile").read_text()
    assert "ARG CAMOFOX_DOWNLOAD_PATCH=1" in dockerfile.split("FROM ", 1)[1]
    assert ('if [ "$CAMOFOX_DOWNLOAD_PATCH" = "1" ]; then node /tmp/camofox-download-progress.mjs '
            '/app/lib/downloads.js; fi') in dockerfile
    assert "!examples/camofox-download-progress.mjs" in (repo / ".dockerignore").read_text().splitlines()
    assert "CAMOFOX_DOWNLOAD_PATCH=0" in (repo / "docs/camofox-operations.md").read_text()


def test_dockerfile_npm_audit_is_fatal_by_default_and_can_only_warn():
    repo = PLUGIN.parents[1]
    dockerfile = (repo / "examples/Dockerfile").read_text()
    assert "ARG NPM_AUDIT_FATAL=1" in dockerfile.split("FROM ", 1)[1]
    assert '{ npm audit --omit=dev --audit-level=high || [ "$NPM_AUDIT_FATAL" = "0" ]; }' in dockerfile
    assert "NPM_AUDIT_FATAL=0" in (repo / "docs/camofox-operations.md").read_text()
