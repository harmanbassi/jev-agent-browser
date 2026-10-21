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
FIRST_CLICK = """        try {
          // First try normal click (respects visibility, enabled, not-obscured)
          await click({ timeout: 3000 });
        } catch (err) {
          // Fallback 1: If intercepted by overlay, retry with force
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_image_bounds_the_dom_click_fallback_or_fails_the_build(tmp_path):
    patch = PLUGIN.parents[1] / "examples/camofox-click-timeout.mjs"
    server = tmp_path / "server.js"
    server.write_text("const before = 1;\n" + CLICK_FALLBACK + FIRST_CLICK)
    out = subprocess.run(["node", str(patch), str(server)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    patched = server.read_text()
    assert "}, undefined, { timeout: Math.max(500, Math.min(3000, remainingBudget())) });" in patched
    # A click Playwright delivered whose navigation is still loading is a success, not a reason
    # to force-click a page that has already gone.
    assert "if (err.message.includes('click action done'))" in patched.split(FIRST_CLICK.splitlines()[3])[1]
    for changed in (patched, CLICK_FALLBACK * 2 + FIRST_CLICK, CLICK_FALLBACK, FIRST_CLICK, "unrelated"):
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
