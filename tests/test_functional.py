"""Real pinned Camofox + installed wheel + deterministic local provider, no paid calls."""
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from test_distribution import installed_package

pytestmark = pytest.mark.skipif(os.environ.get("JEV_FUNCTIONAL") != "1", reason="disposable Docker browser is opt-in")
HTML = b'''<!doctype html><title>Jev fixture</title>
<script>window.testErrors=[];
const recordError=value=>{testErrors.push(value);document.documentElement.dataset.testErrors=JSON.stringify(testErrors)};
document.documentElement.dataset.testErrors='[]';
window.addEventListener('error',e=>recordError(e.message));
window.addEventListener('unhandledrejection',e=>recordError(String(e.reason)));
console.error=(...args)=>recordError(args.join(' '));</script>
<label>Search <input id="query" aria-label="Search"></label>
<button onclick="document.getElementById('result').textContent='Received: '+document.getElementById('query').value">Submit</button>
<p id="result"></p>'''
VISION_HTML = b'''<!doctype html><title>Visual fixture</title>
<style>button{width:180px;height:160px;margin:30px;color:white}</style>
<input aria-label="Private note" value="do-not-upload-this">
<button style="background:blue" onclick="document.getElementById('result').textContent='Wrong selection'">Choose</button>
<button style="background:red" onclick="document.getElementById('result').textContent='Selected red';document.getElementById('result').style.background='lime'">Choose</button>
<p id="result" style="height:80px"></p>'''
OVERLAY_HTML = b'''<!doctype html><title>Covered controls fixture</title>
<button id="behind">Product link behind banner</button>
<input aria-label="Contact" autocomplete="section-order shipping email" value="private-contact">
<select aria-label="Card expiry" autocomplete="section-order billing cc-exp-month">
<option value="private-option" selected>Saved expiry</option><option value="other-private-option">Other expiry</option></select>
<select id="changing" aria-label="Choice"><option value="one">One</option><option value="two">Two</option></select>
<div id="overlay" style="position:fixed;inset:0;z-index:99;background:white">
<button onclick="this.parentElement.remove()"><span>Dismiss banner</span></button>
</div>'''

CODE_HTML = b'''<!doctype html><title>Code and form fixture</title>
<textarea aria-label="file content" style="width:600px;height:80px">MIT License
Copyright (c) 2026 Fixture Authors</textarea>
<textarea aria-label="Contact" autocomplete="email">private-contact-canary</textarea>
<label>Phone <input id="phone" type="tel"></label>
<button onclick="document.getElementById('echo').textContent='Phone length '+document.getElementById('phone').value.length">Send</button>
<p id="echo"></p>'''

# A late script swaps the target for an identical copy after the executor tagged it
# (as a download page that detects the visitor's platform does), so the click on the
# tagged node can never succeed.
SWAP_HTML = b'''<!doctype html><title>Re-render fixture</title>
<input aria-label="Kept" value="typed-before-click">
<div style="position:relative;width:240px;height:60px">
<button id="old" style="position:absolute;inset:0">Download</button>
<button id="new" style="position:absolute;inset:0;display:none">Download</button></div>
<script>let swapped=false;
new MutationObserver(()=>{
  if (swapped || !document.getElementById('old').hasAttribute('data-jev-target')) return;
  swapped=true;
  const cover=document.createElement('div');
  cover.style.cssText='position:fixed;inset:0;z-index:9';
  document.body.append(cover);
  setTimeout(()=>{document.getElementById('old').style.display='none';
    document.getElementById('new').style.display='';cover.remove();},1000);
}).observe(document.getElementById('old'),{attributes:true});</script>'''


@pytest.fixture
def local_provider():
    failures, requests_seen = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data, content_type="application/json"):
            if status >= 500:
                failures.append((self.path, status))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            pages = {"/vision": VISION_HTML, "/overlay": OVERLAY_HTML, "/code": CODE_HTML, "/swap": SWAP_HTML}
            self.reply(200, pages.get(self.path, HTML), "text/html")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests_seen.append(self.path)
            assert self.headers.get("Authorization") == "Bearer fixture-model-key"
            if self.path == "/text":
                response = {"choices": [{"message": {"content": '{"text":"blue mug"}'}}]}
            else:
                state, questions = body["state"], body["questions"]
                if isinstance(state, list):
                    import base64
                    import io
                    from PIL import Image
                    assert "do-not-upload-this" not in json.dumps(state[0])
                    image = Image.open(io.BytesIO(base64.b64decode(state[1]["image_url"]["url"].split(",", 1)[1]))).convert("RGB")
                    if "satisfied" in questions:
                        assert any(g > 200 and r < 50 and b < 50 for r, g, b in image.get_flattened_data())
                        response = {"answers": {"satisfied": {"noul": .99}}}
                    else:
                        state = state[0]
                        operation = "DONE" if "Selected red" in state["page"]["text"] else "CLICK"
                        answers = {"operation": {"choice": operation, "confidence": .99,
                            "probabilities": {k: float(k == operation) for k in questions["operation"]["criteria"]}}}
                        if operation == "CLICK":
                            # Infer the target from actual screenshot pixels, not labels or DOM style.
                            candidates = []
                            for e in state["elements"]:
                                if "CLICK" not in e["operations"]:
                                    continue
                                rect = e["image_rectangle"]
                                pixel = image.getpixel((int(rect["x"] + rect["w"] / 2), int(rect["y"] + 20)))
                                if pixel[0] > 200 and pixel[1] < 50 and pixel[2] < 50:
                                    candidates.append(e["index"])
                            assert len(candidates) == 1
                            target = candidates[0]
                            answers["click_target"] = {"choice": target, "confidence": .99,
                                "probabilities": {k: float(k == target) for k in questions["click_target"]["criteria"]}}
                        response = {"model": "fixture-vision", "answers": answers}
                    self.reply(200, json.dumps(response).encode())
                    return
                if "Received: blue mug" in state["page"]["text"]:
                    operation, target = "DONE", None
                elif any(e.get("value") == "blue mug" for e in state["elements"]):
                    operation = "CLICK"
                    target = next(k for k, v in questions["click_target"]["criteria"].items() if "Submit" in v["element"])
                else:
                    operation = "TYPE_TEXT"
                    target = next(iter(questions["type_text_target"]["criteria"]))

                def answer(choice, options):
                    return {"choice": choice, "confidence": 0.99, "probabilities": {k: float(k == choice) for k in options}}

                answers = {"operation": answer(operation, questions["operation"]["criteria"])}
                if target:
                    head = operation.lower() + "_target"
                    answers[head] = answer(target, questions[head]["criteria"])
                response = {"answers": answers}
            self.reply(200, json.dumps(response).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests_seen
        assert not failures, f"Browser HTTP 500 recorder: {failures}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.fixture(scope="session")
def functional_image():
    image = "jev-functional-" + uuid.uuid4().hex[:12]
    repo = Path(__file__).resolve().parents[1]
    command = ["docker", "build", "--force-rm", "-f", str(repo / "examples/Dockerfile"), "-t", image]
    # Acceptance can also exercise the deployment's existing Firefox build.
    if base := os.environ.get("JEV_TEST_CAMOFOX_BASE_IMAGE"):
        command += ["--build-arg", f"CAMOFOX_BASE_IMAGE={base}"]
    try:
        built = subprocess.run(command + [str(repo)], capture_output=True, text=True, timeout=300)
        assert built.returncode == 0, built.stdout + built.stderr
        yield image
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True, timeout=30)


@pytest.fixture
def disposable_browser(functional_image):
    name, key = "jev-test-" + uuid.uuid4().hex[:12], uuid.uuid4().hex
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    started = subprocess.run(
        ["docker", "run", "-d", "--name", name, "--shm-size=1g", "--network=host",
         "-e", f"CAMOFOX_PORT={port}", "-e", "CAMOFOX_BIND_HOST=127.0.0.1",
         "-e", f"CAMOFOX_ACCESS_KEY={key}", "-e", "CAMOFOX_CRASH_REPORT_ENABLED=false",
         "-e", "MAX_OLD_SPACE_SIZE=512", functional_image],
        capture_output=True, text=True, timeout=180,
    )
    try:
        assert started.returncode == 0, started.stderr
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 90
        while True:
            try:
                if requests.get(url + "/health", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            assert time.monotonic() < deadline, "Browser did not become healthy"
            time.sleep(0.5)
        yield url, key
    finally:
        logs = subprocess.run(["docker", "logs", "--tail", "15", name], capture_output=True, text=True, timeout=10)
        print("Disposable browser logs:", (logs.stdout + logs.stderr)[-5000:])
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, timeout=30)


def test_installed_task_runs_in_real_direct_browser_and_cleans_state(installed_package, local_provider, disposable_browser, tmp_path):
    port, seen = local_provider
    url, key = disposable_browser
    env = {**os.environ, "PYTHONPATH": str(installed_package), "CAMOFOX_URL": url,
           "CAMOFOX_ACCESS_KEY": key, "JEV_OPENROUTER_KEY": "fixture-model-key",
           "JEV_URL": f"http://127.0.0.1:{port}/decisions", "JEV_TEXT_URL": f"http://127.0.0.1:{port}/text",
           "JEV_ALLOW_INSECURE_MODEL_URLS": "1", "JEV_ALLOW_PRIVATE_URLS": "1", "JEV_ALLOWED_HOSTS": "",
           "JEV_FAST_CLICK": "0"}
    # The fixture permits private pages deliberately; no production state or proxy is mounted.
    script = '''
import sys, json
from jev_browser.client import Browser
with Browser() as browser:
    result=browser.start(sys.argv[1], "Search blue mug and submit", max_steps=8, timeout=60)
    assert result["status"]=="done", result
    assert "Received: blue mug" in result["text"], result
    assert result["model_requests"]==4, result
    session=browser._sessions[result["session_id"]]
    assert session.cf.evaluate("({width:innerWidth,height:innerHeight})")=={"width":1120,"height":780}
    # DOM state crosses isolated evaluation realms; page-owned JS globals may not.
    assert json.loads(session.cf.evaluate("document.documentElement.dataset.testErrors"))==[], "Uncaught page error / console.error"
    closed=browser.close(result["session_id"])
    assert closed["status"]=="closed", closed
    assert "warning" not in closed, closed  # Context closure alone is not full saved-profile cleanup.
    assert browser.inspect(result["session_id"])["status"]=="error"
'''
    result = subprocess.run([sys.executable, "-c", script, f"http://127.0.0.1:{port}/fixture"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "resize" not in result.stderr.lower(), result.stderr
    assert seen == ["/decisions", "/text", "/decisions", "/decisions"]
    cli = subprocess.run([sys.executable, "-m", "jev_browser", "doctor", "--help"], cwd=tmp_path,
                         env=env, capture_output=True, text=True, timeout=15)
    assert cli.returncode == 0 and "--probe" in cli.stdout


def test_control_routes_require_auth_even_when_health_is_public(disposable_browser):
    url, _ = disposable_browser
    assert requests.get(url + "/health", timeout=5).status_code == 200
    for headers in ({}, {"Authorization": "Bearer wrong-fixture-key"}):
        response = requests.get(url + "/tabs", params={"userId": "jev-auth-fixture"}, headers=headers, timeout=5)
        assert response.status_code == 401


def test_masked_observation_keeps_form_pixels_and_metadata_private(local_provider, disposable_browser):
    import base64
    import hashlib
    import io
    from PIL import Image
    from jev_browser.camofox import Camofox, Page, READ_STATE
    from jev_browser.policy import URLPolicy

    port, _ = local_provider
    url, key = disposable_browser
    headers = {"Authorization": "Bearer " + key}
    caps = requests.get(url + "/jev/vision", headers=headers, timeout=5).json()
    assert caps == {"protocol": 1, "snapshotHash": hashlib.sha256(READ_STATE.encode()).hexdigest(), "masked": True}
    identity = "jev-mask-" + uuid.uuid4().hex
    target = f"http://127.0.0.1:{port}/fixture"
    cf = Camofox.open(url, identity, identity, target, headers=headers, guard=URLPolicy(allow_private=True))
    try:
        cf.evaluate("document.getElementById('query').value='private-test-value'")
        private_html = """<textarea aria-label="Notes">sensitive-canary-textarea</textarea>
        <input type="password" value="sensitive-canary-password">
        <div contenteditable="true" aria-label="Editor">sensitive-canary-editor</div>
        <div data-jev-private><button>sensitive-canary-private</button></div>
        <iframe srcdoc="<p>sensitive-canary-frame</p>" style="width:100px;height:50px"></iframe>"""
        cf.evaluate("(()=>{document.body.insertAdjacentHTML('beforeend', " + json.dumps(private_html) + ");return true})()")
        state = Page(cf).observe()
        body = {"userId": identity, "expectedUrl": target, "snapshotHash": caps["snapshotHash"]}
        response = requests.post(url + f"/tabs/{cf.tab_id}/jev-observation", headers=headers, json=body, timeout=15)
        assert response.status_code == 200, response.text
        frame = response.json()
        assert "private-test-value" not in json.dumps(frame["safe"])
        assert "sensitive-canary" not in json.dumps(frame["safe"])
        image = Image.open(io.BytesIO(base64.b64decode(frame["image"]["data"]))).convert("RGB")
        rect = next(a["rect"] for a in state["actions"] if a["kind"] == "fill")
        assert image.size == (1120, 780)
        assert image.getpixel((int(rect["x"] + 5), int(rect["y"] + rect["h"] / 2))) == (0, 0, 0)
        masked_rects = cf.evaluate("[...document.querySelectorAll('input,textarea,[contenteditable],[data-jev-private],iframe')].map(e=>e.getBoundingClientRect().toJSON())")
        for r in masked_rects:
            if r["width"] > 0 and r["height"] > 0 and r["bottom"] < image.height:
                assert image.getpixel((int(r["x"] + r["width"] / 2), int(r["y"] + r["height"] / 2))) == (0, 0, 0)
        changed = requests.post(url + f"/tabs/{cf.tab_id}/jev-observation", headers=headers,
                                json={**body, "expectedUrl": "https://other.test"}, timeout=10)
        assert changed.status_code == 409 and "image" not in changed.json()
        denied = requests.post(url + f"/tabs/{cf.tab_id}/jev-observation", json=body, timeout=5)
        assert denied.status_code == 401
    finally:
        assert cf.close_session()


def test_installed_doctor_explains_wrong_key(installed_package, disposable_browser, tmp_path):
    url, _ = disposable_browser
    env = {**os.environ, "PYTHONPATH": str(installed_package), "CAMOFOX_URL": url,
           "CAMOFOX_ACCESS_KEY": "wrong-fixture-browser-key", "JEV_OPENROUTER_KEY": "fixture-model-key"}
    result = subprocess.run([sys.executable, "-m", "jev_browser", "doctor", "--probe"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert not report["ok"] and any(c["name"] == "authentication" for c in report["checks"])
    assert "CAMOFOX_ACCESS_KEY" in result.stdout
    for misleading in ("configuration/version", "idle reaper", "wrong-fixture-browser-key"):
        assert misleading not in result.stdout + result.stderr


def test_installed_snapshot_excludes_covered_targets_and_retains_execution_guard(
        installed_package, local_provider, disposable_browser, tmp_path):
    port, _ = local_provider
    url, key = disposable_browser
    script = '''
import sys, uuid
from jev_browser.camofox import Camofox, Page, StalePage
from jev_browser.policy import URLPolicy
identity="jev-overlay-"+uuid.uuid4().hex
cf=Camofox.open(sys.argv[1], identity, identity, sys.argv[3],
               headers={"Authorization":"Bearer "+sys.argv[2]},
               guard=URLPolicy(allow_private=True))
try:
    page=Page(cf)
    state=page.observe()
    assert not any(a["label"]=="Product link behind banner" for a in state["actions"])
    dismiss=next(a for a in state["actions"] if a["label"]=="Dismiss banner")
    page.act(dismiss,state)  # Nested span is a valid hit inside the observed button.
    state=page.observe()
    target=next(a for a in state["actions"] if a["label"]=="Product link behind banner")
    contact=[a for a in state["actions"] if a["label"] in {"Contact", "Open Contact"}]
    expiry=[a for a in state["actions"] if a["label"]=="Card expiry"]
    assert contact and expiry, (state['actions'], cf.evaluate("[...document.querySelectorAll('input,select')].map(e=>[e.autocomplete,e.getAttribute('autocomplete')])"))
    assert all(a["sensitive"] and a["value"]=='' for a in contact+expiry)
    assert not any(a["kind"]=='select' for a in expiry)
    changing=next(a for a in state["actions"] if a["label"]=='Choice → Two')
    cf.evaluate("(() => {document.getElementById('changing').setAttribute('autocomplete','cc-exp-month');return true;})()")
    try:
        page.act(changing,state)
    except StalePage:
        pass
    else:
        raise AssertionError("a control that becomes sensitive must be refused before input")
    assert cf.evaluate("document.getElementById('changing').value")=='one'
    cf.evaluate("(() => {document.body.insertAdjacentHTML('beforeend', '<div style=position:fixed;inset:0;z-index:100;background:white>New banner</div>'); return true;})()")
    try:
        page.act(target,state)
    except StalePage:
        pass
    else:
        raise AssertionError("a newly covered target must still be refused before input")
finally:
    assert cf.close_session() is not False
'''
    result = subprocess.run(
        [sys.executable, "-c", script, url, key, f"http://127.0.0.1:{port}/overlay"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(installed_package)},
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def test_installed_visual_task_uses_pixels_and_verifies_completion(installed_package, local_provider, disposable_browser, tmp_path):
    port, seen = local_provider
    url, key = disposable_browser
    env = {**os.environ, "PYTHONPATH": str(installed_package), "CAMOFOX_URL": url,
           "CAMOFOX_ACCESS_KEY": key, "JEV_OPENROUTER_KEY": "fixture-model-key",
           "JEV_URL": f"http://127.0.0.1:{port}/decisions", "JEV_ALLOW_INSECURE_MODEL_URLS": "1",
           "JEV_ALLOW_PRIVATE_URLS": "1", "JEV_ALLOWED_HOSTS": "", "JEV_VISION_ENABLED": "1"}
    script = '''import sys, json
from jev_browser.client import Browser
with Browser() as browser:
    out=browser.start(sys.argv[1], "Choose the red button. Finish when Selected red appears on a green banner.",
                      require_visual=True, timeout=90)
    assert out["status"]=="done", out
    assert out["vision"]["calls"]==3 and out["vision"]["verified"], out
    assert len(out["steps"])==1 and out["steps"][0]["kind"]=="click", out
    assert "do-not-upload-this" not in json.dumps(out), out
    assert "data:image" not in json.dumps(out), out
    assert browser.close(out["session_id"])["status"]=="closed"
'''
    result = subprocess.run([sys.executable, "-c", script, f"http://127.0.0.1:{port}/vision"], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=130)
    assert result.returncode == 0, result.stdout + result.stderr
    assert seen == ["/decisions"] * 3


def test_installed_snapshot_reads_code_views_and_the_supervisor_fills_sensitive_fields(
        installed_package, local_provider, disposable_browser, tmp_path):
    port, seen = local_provider
    url, key = disposable_browser
    env = {**os.environ, "PYTHONPATH": str(installed_package), "CAMOFOX_URL": url,
           "CAMOFOX_ACCESS_KEY": key, "JEV_OPENROUTER_KEY": "fixture-model-key",
           "JEV_ALLOW_PRIVATE_URLS": "1", "JEV_ALLOWED_HOSTS": ""}
    script = '''import sys
from jev_browser.client import Browser
with Browser() as browser:
    sid=browser.open(sys.argv[1])["session_id"]
    page=browser.snapshot(sid)
    assert "Copyright (c) 2026 Fixture Authors" in page["text"], page
    assert "private-contact-canary" not in str(page), page
    phone=next(e for e in page["elements"] if e["label"]=="Phone" and "TYPE_TEXT" in e["operations"])
    send=next(e for e in page["elements"] if e["label"]=="Send")
    typed=browser.act(sid, phone["index"], "type", "5550100")
    assert typed["status"]=="ready" and "5550100" not in str(typed), typed
    assert browser.act(sid, None, "press", "Tab")["status"]=="ready"
    page=browser.snapshot(sid)
    send=next(e for e in page["elements"] if e["label"]=="Send")
    out=browser.act(sid, send["index"], "click")
    assert out["status"]=="ready" and out["changed"], out
    assert "Phone length 7" in browser.snapshot(sid)["text"]
    assert browser.close(sid)["status"]=="closed"
'''
    result = subprocess.run([sys.executable, "-c", script, f"http://127.0.0.1:{port}/code"], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert seen == []  # the supervisor path makes no model calls


SWAP_CHECK = '''import sys, time, uuid
from jev_browser.camofox import Camofox, Page, StalePage
from jev_browser.policy import URLPolicy
identity="jev-swap-"+uuid.uuid4().hex
cf=Camofox.open(sys.argv[1], identity, identity, sys.argv[3],
               headers={"Authorization":"Bearer "+sys.argv[2]}, guard=URLPolicy(allow_private=True))
try:
    page=Page(cf)
    state=page.observe()
    target=next(a for a in state["actions"] if a["label"]=="Download")
    started=time.monotonic()
    try:
        page.act(target, state)
    except StalePage:
        pass
    else:
        raise AssertionError("a target swapped out after tagging must not count as clicked")
    assert time.monotonic()-started < 25, time.monotonic()-started
    state=page.observe()  # the same tab survives, with its form state
    assert any(a.get("value")=="typed-before-click" for a in state["actions"]), state["actions"]
finally:
    cf.close_session()
'''


def test_installed_click_on_a_target_swapped_after_tagging_is_stale_not_a_destroyed_tab(
        installed_package, local_provider, disposable_browser, tmp_path):
    port, _ = local_provider
    url, key = disposable_browser
    result = subprocess.run([sys.executable, "-c", SWAP_CHECK, url, key, f"http://127.0.0.1:{port}/swap"],
                            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(installed_package)},
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
