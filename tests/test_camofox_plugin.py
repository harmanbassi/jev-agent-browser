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


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_image_bounds_the_dom_click_fallback_or_fails_the_build(tmp_path):
    patch = PLUGIN.parents[1] / "examples/camofox-click-timeout.mjs"
    server = tmp_path / "server.js"
    server.write_text("const before = 1;\n" + CLICK_FALLBACK)
    out = subprocess.run(["node", str(patch), str(server)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "}, undefined, { timeout: Math.max(500, Math.min(3000, remainingBudget())) });" in server.read_text()
    for changed in (server.read_text(), CLICK_FALLBACK * 2, "unrelated"):  # already patched, ambiguous, absent
        server.write_text(changed)
        out = subprocess.run(["node", str(patch), str(server)], capture_output=True, text=True)
        assert out.returncode != 0 and "not found exactly once" in out.stderr


def test_dockerfile_applies_the_click_patch_and_the_build_context_includes_it():
    repo = PLUGIN.parents[1]
    dockerfile = (repo / "examples/Dockerfile").read_text()
    assert "RUN node /tmp/camofox-click-timeout.mjs /app/server.js" in dockerfile
    assert "!examples/camofox-click-timeout.mjs" in (repo / ".dockerignore").read_text().splitlines()
