import asyncio
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from jev_browser import cli


class FakeBrowser:
    def __init__(self):
        self.calls = []
        self.finished = threading.Event()

    def open(self, url):
        self.calls.append(url)
        return {"status": "ready", "session_id": "s1"}

    def start(self, url, goal, **kw):
        return {"status": "done", "text": "Found it"}

    def run(self, session_id, goal, **kw):
        return {"status": "done", "session_id": session_id, "text": goal}

    def inspect(self, sid):
        return {"status": "paused", "session_id": sid}

    def snapshot(self, sid):
        return {"status": "ready", "session_id": sid, "elements": []}

    def act(self, sid, element_id, action, value=None):
        self.calls.append(("act", sid, element_id, action, value))
        return {"status": "ready", "session_id": sid, "changed": True}

    def cancel(self, sid):
        self.finished.set()
        return {"status": "cancelling"}

    def close(self, sid):
        self.calls.append(("close", sid))
        return {"status": "closed"}

    def shutdown(self):
        self.calls.append("shutdown")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown()


def test_cli_json_exit_codes_and_cleanup(monkeypatch, capsys):
    b = FakeBrowser()
    monkeypatch.setattr(cli, "Browser", lambda: b)
    assert cli.main(["run", "https://a.test", "find it"]) == 0
    assert json.loads(capsys.readouterr().out)["text"] == "Found it"
    assert b.calls == ["shutdown"]
    monkeypatch.setattr(b, "start", lambda *a, **kw: {"status": "paused"})
    assert cli.main(["run", "https://a.test", "g"]) == 3
    capsys.readouterr()

    def invalid():
        raise ValueError("invalid config")

    monkeypatch.setattr(cli, "Browser", invalid)
    assert cli.main(["run", "https://a.test", "g"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid config"


def test_cli_doctor_and_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(cli, "diagnose", lambda **kw: {"ok": False})
    assert cli.main(["doctor"]) == 1
    capsys.readouterr()

    def interrupted(**kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "diagnose", interrupted)
    assert cli.main(["doctor"]) == 130
    assert json.loads(capsys.readouterr().out)["reason"] == "cancelled"


def test_cli_reports_cleanup_warning_in_json(monkeypatch, capsys):
    browser = FakeBrowser()
    browser.cleanup_warnings = ["saved state needs cleanup"]
    monkeypatch.setattr(cli, "Browser", lambda: browser)
    assert cli.main(["run", "https://a.test", "g"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == browser.cleanup_warnings


def test_missing_mcp_extra_reports_source_install_on_stderr(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "jev_browser.mcp_server", None)
    assert cli.main(["mcp"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "python -m pip install 'jev-browser[mcp]'" in captured.err


def test_mcp_tools_share_browser_and_return_structured_results():
    pytest.importorskip("mcp")
    from jev_browser.mcp_server import create_server
    b = FakeBrowser()
    server = create_server(b)

    async def exercise():
        names = {t.name for t in await server.list_tools()}
        assert names == {"browser_open", "browser_task", "browser_inspect", "browser_cancel", "browser_close",
                         "browser_snapshot", "browser_act"}
        for name, args, expected in [
            ("browser_open", {"url": "https://a.test"}, "ready"),
            ("browser_task", {"session_id": "s1", "goal": "g"}, "done"),
            ("browser_snapshot", {"session_id": "s1"}, "ready"),
            ("browser_act", {"session_id": "s1", "element_id": "3", "action": "type", "value": "x"}, "ready"),
            ("browser_act", {"session_id": "s1", "action": "press", "value": "Enter"}, "ready"),
            ("browser_inspect", {"session_id": "s1"}, "paused"),
            ("browser_cancel", {"session_id": "s1"}, "cancelling"),
            ("browser_close", {"session_id": "s1"}, "closed"),
        ]:
            result = await server.call_tool(name, args)
            assert not result.is_error and result.structured_content["status"] == expected

    asyncio.run(exercise())
    assert ("act", "s1", "3", "type", "x") in b.calls and ("act", "s1", None, "press", "Enter") in b.calls


def test_mcp_cancellation_reaches_worker():
    pytest.importorskip("mcp")
    from jev_browser.mcp_server import create_server
    b, entered = FakeBrowser(), threading.Event()

    def run(*a, **kw):
        entered.set()
        assert b.finished.wait(3)
        return {"status": "paused"}

    b.run = run
    server = create_server(b)

    async def exercise():
        task = asyncio.create_task(server.call_tool("browser_task", {"session_id": "s1", "goal": "g"}))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert b.finished.is_set()

    asyncio.run(exercise())


def test_real_mcp_stdio_handshake_and_tools(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def exercise():
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "jev_browser", "mcp"], cwd=str(tmp_path),
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PATH": os.environ["PATH"]},
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                info = await session.initialize()
                assert info.server_info.name == "jev-browser"
                assert len((await session.list_tools()).tools) == 7
                out = await session.call_tool("browser_inspect", {"session_id": "unknown"})
                assert out.structured_content["status"] == "error"

    asyncio.run(exercise())


def test_cli_forwards_visual_and_diagnostic_options(monkeypatch, capsys):
    b = FakeBrowser()
    calls = []
    monkeypatch.setattr(cli, "Browser", lambda: b)
    monkeypatch.setattr(b, "start", lambda *a, **kw: calls.append(kw) or {"status": "done"})
    assert cli.main(["run", "https://a.test", "red", "--vision", "always", "--require-visual"]) == 0
    assert calls[0]["vision"] == "always" and calls[0]["require_visual"]
    monkeypatch.setattr(cli, "diagnose", lambda **kw: calls.append(kw) or {"ok": True})
    assert cli.main(["doctor", "--vision", "--vision-model-probe"]) == 0
    assert calls[1]["vision"] and calls[1]["vision_model_probe"]
    capsys.readouterr()


def test_mcp_forwards_visual_controls_and_advertises_requirement():
    pytest.importorskip('mcp')
    from jev_browser.mcp_server import create_server
    browser = FakeBrowser()
    seen = []
    browser.run = lambda *a, **kw: seen.append(kw) or {'status': 'paused'}
    server = create_server(browser)
    async def exercise():
        tools = (await server.list_tools())
        task = next(t for t in tools if t.name == 'browser_task')
        assert 'require_visual' in task.input_schema['properties']
        result = await server.call_tool('browser_task', {'session_id': 's', 'goal': 'red',
                                                        'vision': 'always', 'require_visual': True})
        assert result.structured_content['status'] == 'paused'
    asyncio.run(exercise())
    assert seen[0]['vision'] == 'always' and seen[0]['require_visual']


def test_browser_act_does_not_overstate_what_stays_from_the_model():
    pytest.importorskip("mcp")
    from jev_browser.mcp_server import create_server

    async def describe():
        return next(t for t in await create_server(FakeBrowser()).list_tools() if t.name == "browser_act").description

    text = " ".join(asyncio.run(describe()).split())
    assert "never sent" not in text and "by this call" in text and "later observations" in text
