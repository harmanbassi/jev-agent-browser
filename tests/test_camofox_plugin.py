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
