"""Exercise the artifact users install, outside the source directory."""
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import tarfile
import tomllib
import pytest


@pytest.fixture
def installed_package(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    # Only committed/staged source belongs in a release, never local secrets/state.
    for name in subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0"):
        if name:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / name, target)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-cache-dir",
         "-w", str(tmp_path / "wheels"), str(source)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheel, = (tmp_path / "wheels").glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "jev_browser/snapshot.js" in names and "jev_browser/plugin.yaml" in names
        assert not any(n.startswith(("tests/", "camofox_plugin/", ".env")) for n in names)
        assert any(n.endswith("/LICENSE-jev-ultrafast") for n in names)
    installed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-cache-dir", "--target",
         str(tmp_path / "installed"), str(wheel)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    probe = subprocess.run(
        [sys.executable, "-c", "import sys; from jev_browser.loop import run_task; "
         "from jev_browser.camofox import READ_STATE; "
         "assert 'document.body' in READ_STATE; assert 'tools' not in sys.modules"],
        cwd=tmp_path, env={**env, "PYTHONPATH": str(tmp_path / "installed")},
        capture_output=True, text=True, timeout=15,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    return tmp_path / "installed"


def test_wheel_installs_and_imports_without_hermes(installed_package):
    assert (installed_package / "jev_browser" / "snapshot.js").is_file()


def test_source_archive_contains_security_setup_and_builds_a_wheel(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    built = subprocess.run([sys.executable, "-m", "build", "--sdist", "--no-isolation",
                            "--outdir", str(tmp_path), str(repo)], capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    archive, = tmp_path.glob("*.tar.gz")
    with tarfile.open(archive) as source:
        names = {name.split("/", 1)[-1] for name in source.getnames()}
    assert {"SECURITY.md", "TESTING.md", "CHANGELOG.md", "docs/agent-setup.md", "docs/camofox-operations.md",
            "docs/troubleshooting.md", "docs/releasing.md", ".env.example", ".dockerignore", "examples/compose.yaml", "examples/Dockerfile",
            "examples/camofox-click-timeout.mjs", "examples/camofox-download-progress.mjs",
            "docs/hermes-routing.md", "integrations/hermes/tool-search-keep.patch", "tests/helpers.py"} <= names
    assert ".env" not in names
    assert not any(n.startswith((".claude/", "scripts/", "docs/specs/")) for n in names)
    wheel = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                            "--no-cache-dir", "-w", str(tmp_path / "wheels"), str(archive)],
                           capture_output=True, text=True, timeout=60)
    assert wheel.returncode == 0, wheel.stdout + wheel.stderr


def test_tracked_release_tree_excludes_private_development_tooling():
    repo = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    assert not any(n.startswith((".claude/", "scripts/gate", "docs/specs/")) for n in names)
    assert "scripts/mutate-python.py" not in names and "scripts/test-stack.sh.example" not in names


def test_plugin_manifest_version_matches_the_package_version():
    repo = Path(__file__).resolve().parents[1]
    package = tomllib.loads((repo / "pyproject.toml").read_text())["project"]["version"]
    plugin, = re.findall(r"^version: *(\S+)$", (repo / "jev_browser/plugin.yaml").read_text(), re.M)
    assert plugin == package
