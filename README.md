# Jev Agent Browser

A browser execution layer for agents: [TypeSafe's Jev](https://docs.typesafe.ai/introduction)
chooses individual operations, [Camofox](https://github.com/jo-inc/camofox-browser)
executes real mouse/keyboard input, and your agent handles planning and pauses.
Use the Python library, CLI, local MCP server, or native Hermes plugin. Claude
and Codex can supervise it through MCP; their models are not bundled here.

Unofficial: not affiliated with or endorsed by TypeSafe, OpenRouter, Camofox
(jo-inc) or Browser Use; their names are their owners' trademarks.

Adapted from [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)
(MIT). Requires Python 3.11+, a running Camofox service, and your own OpenRouter
key with access to Jev's decisions endpoint. **A proxy is optional.** Requests
cost money at your provider's rates; the package includes no model credits.
Read [SECURITY.md](https://github.com/harmanbassi/jev-agent-browser/blob/main/SECURITY.md) before browsing private or authenticated pages.

Codex or Claude supplies the goal and checks the result; Jev chooses observed
page actions and Camofox executes them. The standalone interfaces work without
Hermes. See [agent setup](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/agent-setup.md) for routing instructions and
[Camofox operations](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/camofox-operations.md) for supported versions and upgrades.

The repository is named `jev-agent-browser`; the Python distribution and command
remain `jev-browser`, and the import/plugin name remains `jev_browser`.

## Install and try it

Prerequisites: Python 3.11+, Docker with Compose to run the Camofox server
(unless you already have one), and an OpenRouter API key with access to Jev.

The package is on PyPI: `python -m pip install 'jev-browser[mcp]'`. The clone
below adds the example settings file and the Camofox build.

```bash
git clone https://github.com/harmanbassi/jev-agent-browser.git
cd jev-agent-browser
python3 -m venv .venv
source .venv/bin/activate
python -m pip install 'jev-browser[mcp]'
cp .env.example .env
chmod 600 .env
```

Edit `.env`: supply your OpenRouter key and generate a long random browser access
key (for example, `python -c 'import secrets; print(secrets.token_hex(32))'`). Set
both browser-key entries to that same value if using Hermes. Keep `.env` private.
Quote values containing shell characters such as spaces, `#` or `$` before
sourcing the file. If changing the published browser port, update `CAMOFOX_URL`
to match it as well.
On Windows use `.venv\Scripts\Activate.ps1` and set the environment through your
shell or agent settings. MCP is optional: `pip install jev-browser` installs the core/CLI.

If you already have Camofox, set `CAMOFOX_URL` and its authentication key and keep
that service. Otherwise build the pinned Camofox 1.18.1 image plus its dependency
security updates with Docker Compose (the first build needs npm registry access):

```bash
docker compose --env-file .env -f examples/compose.yaml up -d --build --wait
# Export the file you just edited into this shell (review it before sourcing).
set -a
. ./.env
set +a
jev-browser doctor
jev-browser doctor --probe
jev-browser run https://en.wikipedia.org/wiki/Main_Page "Find and open the article about Gödel's incompleteness theorems"
```

`doctor` checks configuration and health without a paid model call. `--probe`
opens a throwaway example.com tab and tests the required evaluate route; it can
use proxy bandwidth. The run command returns JSON and closes its isolated session.
Exit codes: 0 done, 1 task/diagnostic error, 2 configuration/usage error, 3 paused,
130 interrupted. CLI tasks are one-shot; use MCP or Python to resume a session.
If Jev returns 401/403, check model access and your key; 429 indicates provider
limits. The alpha decisions API can change independently of this project.
For browser authentication failures, cleanup warnings and missing tools, see
[troubleshooting](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/troubleshooting.md). `doctor --probe` verifies browser
control and cleanup; a successful public `/health` check alone cannot verify a key.

### CLI reference

| Command | Options |
| --- | --- |
| `jev-browser run URL GOAL` | `--max-steps N` (default 25, at most 100), `--max-model-calls N` (default 100, at most 500), `--timeout SECONDS` (default 300, at most 900), `--vision {off,auto,always}`, `--require-visual` / `--no-require-visual`. Prints one JSON result and closes its session. |
| `jev-browser doctor` | `--probe` opens and closes an example.com tab to check `/evaluate`; `--vision` checks masked capture without uploading an image; `--vision-model-probe` makes one paid image request. |
| `jev-browser mcp` | Serves the MCP tools over stdio (requires the `mcp` extra). |

## Claude Code, Codex and other MCP clients

Install the `mcp` extra above. Use the **absolute** path to the installed
`jev-browser` executable (`command -v jev-browser`; Windows: `where jev-browser`).
Export the client environment before launching your agent, or configure its
secret injection. Nothing auto-loads `.env` from an agent's working directory.

Claude Code ([official MCP guide](https://code.claude.com/docs/en/mcp)):

```bash
claude mcp add --transport stdio jev-browser -- /absolute/path/.venv/bin/jev-browser mcp
```

Codex ([official MCP guide](https://developers.openai.com/codex/mcp)): add this to
`~/.codex/config.toml` and launch Codex from the configured environment:

```toml
[mcp_servers.jev-browser]
command = "/absolute/path/.venv/bin/jev-browser"
args = ["mcp"]
env_vars = ["JEV_OPENROUTER_KEY", "OPENROUTER_API_KEY", "CAMOFOX_URL", "CAMOFOX_ACCESS_KEY", "CAMOFOX_API_KEY", "JEV_ALLOWED_HOSTS", "JEV_ALLOW_PRIVATE_URLS", "JEV_MODEL", "JEV_TEXT_MODEL", "JEV_URL", "JEV_TEXT_URL", "JEV_VISION_ENABLED", "JEV_VISION_MODE", "JEV_VISION_MODEL", "JEV_VISION_MAX_CALLS", "JEV_VISION_BOX"]
tool_timeout_sec = 360
```

A generic MCP client can launch the same command with `args: ["mcp"]` and an
`env` map containing its keys and browser URL. Use a separate server process per
agent/owner. Only stdio transport is supported; no public MCP listener is opened.
Configure the client's tool timeout above your chosen task timeout (default 300s).
Installing the package alone does not register it in an agent's tool list. Check
the client's active MCP tools and credentials after starting a new session. The
MCP interface opens its own isolated identities; it does not adopt a live Hermes tab.

Tool flow:

1. `browser_open(url)` returns an isolated `session_id`.
2. `browser_task(session_id, goal)` runs or continues a task.
3. On `paused`, read `reason`, `fallback`, `text` and `elements`. Either give
   `browser_task` a clearer goal, or do the step yourself: `browser_snapshot`
   returns the page text and element ids, and `browser_act(session_id, action,
   element_id?, value?)` clicks, types, selects, presses a key (Enter, Tab,
   Escape, arrows...) or scrolls on those ids, then `browser_task` continues the
   same session. `sensitive_action` (for example a phone field) is never retried
   by Jev; enter such values with `browser_act` only when the user supplied them
   and approved the step. Once filled, the field shows `[filled]` and Jev
   continues without pausing on it again. See [SECURITY.md](https://github.com/harmanbassi/jev-agent-browser/blob/main/SECURITY.md) for this path's limits.
4. `browser_inspect` retrieves the last result/running state; `browser_cancel`
   requests cancellation. `browser_close` destroys the owned context and attempts
   saved-state removal (legacy authentication failures return a warning). If busy,
   retry close after cancellation completes.

Sessions are process-local, capped at 16, and expire after 15 idle minutes when
next accessed or a new session is opened. Server shutdown attempts cleanup.

### Task results

Every interface (Python, CLI, MCP, Hermes) returns these result fields, except
where a row names the interfaces:

| Field | Meaning |
| --- | --- |
| `status` | `done`, `paused` (with `reason`) or `error` |
| `url`, `title`, `text` | The last page read, when it passed the URL policy |
| `elements` | On `paused`: the observed controls Jev could act on |
| `confidence`, `target_confidence`, `detail` | On `low_confidence`: the operation and target confidence below the floor; `detail` when the goal check contradicted `DONE` |
| `field` | On `missing_value`: the label of the field the goal gives no value for |
| `fallback` | On `paused` (Python, CLI, MCP): what the supervising agent should do next. It names the MCP tools; Python has the same `Browser.snapshot`/`Browser.act`. A CLI run is one-shot, so rerun with a clearer goal or use MCP/Python to act on the same session |
| `next`, `success` | Hermes, instead of `fallback`: guidance for this status, and whether it was not an error |
| `session_id` | Python, CLI, MCP: the session the task ran in (already closed after a CLI run) |
| `steps` | Executed actions: `action` (the control's label), `kind` (`click`, `fill`, `select`, `scroll`, `wait`, or `recover` for a reopened tab), `text` (the value Jev typed, else null), `from_url` (the page they ran on), `url_after` (where they led, once that page passed the URL policy), their confidences and `page_changed`. `effect` marks a click the browser abandoned after sending it (`taken` if the page moved, else `uncertain`; an identical `uncertain` click is not repeated: `action_uncertain` pause); `download` names a file it started, renamed `download_failed` if that download later failed (the click may then be repeated); `tab_lost` marks the action during which the browser destroyed the tab |
| `jev_calls`, `model_requests` | Decisions made; model HTTP requests including retries/helpers |
| `models` | The decision models that answered, as reported by the provider |
| `downloads` | Files that clicks started downloading; a click that started one is not repeated (`download_started` pause) |
| `recoveries` | Tabs the browser destroyed during a read that were reopened on the latest page (at most 2), also listed in `steps`. A tab lost during an action pauses as `tab_lost` instead, because the action may have taken effect |
| `usage` | Reported `input_tokens`/`output_tokens` (and `cost` where the provider reports it) for the task, totalled and `by_model` |
| `vision` | With vision allowed: image calls, captures, `uploaded_bytes`, escalations, verification |
| `completion_probability` | The last decision's goal check: probability the goal is already met |
| `done_by` | `goal_check` when that check (at least 0.9), not the operation choice, finished the task |
| `elapsed_ms` | Task duration in milliseconds |
| `warnings` | CLI: browser cleanup warnings from closing the session |

| Pause `reason` | Meaning |
| --- | --- |
| `step_budget` | `max_steps` actions ran; continue with a fresh budget |
| `model_budget` | `max_model_calls` model HTTP requests were used |
| `timeout` | The task deadline passed |
| `cancelled` | The task was cancelled (`browser_cancel`, `Browser.cancel`, or an interrupted CLI run) |
| `no_progress` | The last three actions changed nothing, or were the same action |
| `need_guidance` | Jev asked for guidance instead of choosing an action |
| `blocked` | Jev judged the goal blocked on this page |
| `low_confidence` | The chosen operation or target was below its confidence floor |
| `sensitive_action` | The next step is a sign-in, payment, destructive or personal-data control Jev never acts on |
| `missing_value` | The goal does not supply a value for `field` |
| `action_uncertain` | The browser gave up on the last input after sending it and the page has not changed; it may have taken effect |
| `download_started` | This click already started a download; it is not repeated |
| `tab_lost` | The browser destroyed the tab during an action, which may have taken effect |
| `vision_budget`, `vision_capture_budget` | The image request or capture budget is used up |
| `vision_completion_unverified` | A `require_visual` task's image did not establish the goal |
| `vision_capture_unavailable`, `vision_capture_failed`, `vision_invalid_observation`, `vision_url_blocked`, `vision_expired_observation`, `vision_target_ambiguous` | Visual evidence could not be captured or used; see [visual browsing](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/vision.md#common-pauses) |

Errors carry a readable message in `reason` instead. `vision_disabled` and
`vision_dependency_missing` are errors returned before a task starts.

Every decision also asks Jev, in the same request, whether the goal is already
met. A confident yes (at least 0.9) finishes the task where the operation head
leaves room for it: the head gave `DONE` at least 0.15, or its chosen action is
below its floor. It never overrides `NEED_GUIDANCE`, `BLOCKED` or a confident
action. A confident no (at most 0.2) overrules a `DONE` choice; the next-best
operation is scored on its own probability and must clear the usual floor, or
the task pauses as `low_confidence` with a `detail`. Goals that ask for an action
(open, submit, send) are not met by a page that only offers it.

Duplicate links (the same label and the same real `href`, such as a header and
footer "Downloads") share their probability before the target confidence floor
applies, and Jev acts on the copy it preferred. Script-handled links (`#...`,
`javascript:`) and controls without a shared destination, such as an
"Add to cart" button on every row, are never pooled.

## Optional visual browsing

Jev 1.14 can use images alongside page text. Vision is **off by default** and
experimental. Install `python -m pip install 'jev-browser[mcp,vision]'`, rebuild the browser
image from this checkout, then explicitly permit masked image uploads with
`JEV_VISION_ENABLED=1` in the environment of your Python/CLI/MCP process or
Hermes profile. Your OpenRouter key must have access to `typesafe/jev-1.14`.
The image model is pinned independently of the text model.

For appearance, pictures, colors or layout goals, your agent must call
`browser_task(..., require_visual=true)` (Python: `require_visual=True`) or use
`jev-browser run URL GOAL --require-visual`. This starts with visual evidence
and requires a separate visual completion check. A resumed MCP/Python/Hermes
session preserves that requirement when omitted; explicitly pass false to clear
it. `vision="always"` uses images from the start; `auto` escalates on low
confidence, blocked decisions or no progress. Automatic escalation cannot infer
all visual intent from a natural-language goal: use `require_visual` explicitly.
Task options cannot enable uploads if the operator has disabled them.

`jev-browser doctor --vision` checks compatible masked capture on a throwaway
page without uploading an image. `--vision-model-probe` explicitly makes a paid
image request. The regular doctor remains read-only and makes no paid requests.
Old Camofox servers continue to support text browsing; visual tasks pause when
the masked endpoint is unavailable. See [visual browsing](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/vision.md) for
privacy boundaries, budgets, installation and failure reasons.

## Hermes

Install the core into **Hermes' Python environment**, then link this checkout's
plugin directory (the package stays import-light at plugin discovery):

```bash
/path/to/hermes/venv/bin/python -m pip install /absolute/path/to/jev-agent-browser
ln -s /absolute/path/to/jev-agent-browser/jev_browser ~/.hermes/plugins/jev_browser
```

Merge these settings into Hermes' existing `config.yaml`; preserve other enabled
plugins and toolsets:

```yaml
plugins:
  enabled: [jev_browser]
# Add browser_task beside browser in each platform_toolsets entry you use.
# Where the Hermes version supports explicit browser selection:
browser:
  cloud_provider: camofox
```

Set `CAMOFOX_URL`, `OPENROUTER_API_KEY` (or `JEV_OPENROUTER_KEY`) in Hermes' runtime
secrets/environment. On Camofox with global access-key authentication, set Hermes'
`CAMOFOX_API_KEY` to the server's `CAMOFOX_ACCESS_KEY`, since its native browser
adapter sends that key as a Bearer token. Restart Hermes after installing/enabling
its plugin. This requires a Hermes version providing `ctx.register_tool` and the
`tools.browser_camofox`/`tools.browser_tool` APIs used by this plugin.

The tool remains `browser_task(goal, url?, max_steps?, max_model_calls?, timeout?, vision?, require_visual?)`.
It uses Hermes' existing tab, cookie identity, auth headers, URL checks and website
policy. Omitting `url` continues the same tab; `browser_*` tools remain its manual
fallback. Existing proxy/persistence settings stay on the existing Camofox server.
On Hermes versions with profile secret scopes, model keys, endpoints and settings
are resolved within the active profile; missing credentials never fall back to a
different profile's environment. Older Hermes versions retain environment loading.
For a personal Hermes profile that should keep its open tab across turns,
merge this optional native setting as well:

```yaml
browser:
  camofox:
    managed_persistence: true
    adopt_existing_tab: true
```

Hermes can clear its local tab reference when a turn finishes. Adoption restores
an open managed tab, preferring its session label and otherwise the latest tab
in that cookie identity. Use a separate identity/profile per independent owner;
this setting is intended for a personal browser with coordinated use. Browser
restarts and idle reaping can still remove tabs, requiring a fresh URL. Saved
cookies and live page state are different forms of persistence.

The native Hermes adapter is tested with Hermes v0.21.6; other Hermes versions
can also use the standalone MCP/CLI interfaces.

The plugin supplies Jev-first browsing instructions on Hermes versions supporting
plugin prompt sections. This covers ordinary requests and follow-ups, manual
fallbacks, and discovery when Hermes defers plugin tools. **Enabled does not mean
directly visible:** check the model's actual tool list, not only plugin registration.
See [Hermes routing and acceptance tests](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/hermes-routing.md), including an
optional, version-tested host patch to keep `browser_task` directly visible.

## Python

```python
from jev_browser.client import Browser

with Browser() as browser:
    result = browser.start("https://example.com", "Read the page title")
    if result["status"] == "paused":
        result = browser.run(result["session_id"], "Read the visible heading")
    print(result)
```

`browser.snapshot(session_id)` and `browser.act(session_id, element_id, action,
value=None)` are the MCP `browser_snapshot`/`browser_act` supervisor tools. The
other MCP tools map the same way:

```python
browser = Browser(max_sessions=16, idle_seconds=900)  # the defaults
sid = browser.open("https://example.com")["session_id"]  # no model call yet
result = browser.run(sid, "Read the page title")
browser.inspect(sid)   # last result, or {"status": "running"}
browser.cancel(sid)    # cooperative; a running task pauses as cancelled
browser.close(sid)     # destroys the session's identity and saved state
browser.shutdown()     # closes every session (the context manager does this)
```

The lower-level `Camofox`, `Page`, and `run_task` interfaces remain available for
custom drivers. `run_task` defaults to the public-page URL policy. Supply an
explicit `URLPolicy(allow_private=True)` only when you intend to send private
page data to the model. Pass the same policy to `Camofox.open(..., guard=policy)`.
Low-level `cf.close()` closes one tab; `cf.close_session()` destroys the entire
identity and saved state, so use it only for identities you own.

## Optional proxy and configuration

Leave `PROXY_*` empty for direct browser connections. To use a proxy, set those
variables in `.env` and recreate **your** Compose service. Proxy credentials are
passed only to Camofox, never to Jev. The Python package doesn't configure or
bypass browser-side proxies. Connecting to an existing proxied service preserves
its routing. Browser proxies and standard HTTP(S)_PROXY/NO_PROXY variables for
Python's HTTP clients are separate; ensure control requests can reach loopback.

The Compose sample sets Camofox's Node heap budget to 512 MiB through
`CAMOFOX_HEAP_MB` / `MAX_OLD_SPACE_SIZE`. The image's 128 MiB default exhausted
its heap during a longer interactive acceptance run and restarted the service,
losing live tabs. This is the Node heap budget, not a total container memory
limit: Firefox and other allocations need additional memory. Existing Camofox
operators should check their service's heap budget separately; the Python
package cannot change it. A browser restart can lose tabs while saved cookies
survive, so supervisors must reopen the last verified URL when no page remains.

For local/staging sites, use a separate direct Camofox service and explicitly
permit private pages; a globally proxied browser might not reach them. Never send
local traffic through a metered proxy accidentally. Metadata endpoints remain
blocked even with `JEV_ALLOW_PRIVATE_URLS=1`.

| Setting | Default / purpose |
| --- | --- |
| `CAMOFOX_URL` | `http://127.0.0.1:9377` |
| `CAMOFOX_ACCESS_KEY`, fallback `CAMOFOX_API_KEY` | Browser Bearer token |
| `JEV_OPENROUTER_KEY`, fallback `OPENROUTER_API_KEY` | Model API key |
| `JEV_MODEL` | `~typesafe/jev-latest` |
| `JEV_TEXT_MODEL` | `inception/mercury-2.5` |
| `JEV_URL`, `JEV_TEXT_URL` | OpenRouter decisions/chat endpoints |
| `JEV_ALLOWED_HOSTS` | Empty; otherwise exact comma-separated page hosts |
| `JEV_ALLOW_PRIVATE_URLS` | `0`; standalone private-page opt-in |
| `JEV_FAST_CLICK` | `0`; optional [Camofox plugin](https://github.com/harmanbassi/jev-agent-browser/blob/main/camofox_plugin/README.md) |
| `JEV_ALLOW_INSECURE_CAMOFOX` | `0`; permit a remote cleartext (`http://`) Camofox on a trusted network |
| `JEV_ALLOW_INSECURE_MODEL_URLS` | `0`; permit cleartext development model endpoints |
| `JEV_VISION_*` | Optional visual browsing; see the [vision settings](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/vision.md#install-and-configure) |

Task defaults: 25 executed steps, 100 model HTTP requests including helper/retry
calls, 300 seconds. Maximums: 100 steps, 500 requests, 900 seconds. Cancellation
is cooperative. Private-page configuration in Hermes remains Hermes' own policy.
Known limitations: top-level DOM interaction, no general iframe/upload/popup
support, no login/payment automation, model-assessed completion. Viewport resize
works with the recommended image's pinned Playwright version. Other images' resize
stalls warn after five seconds and continue using the actual viewport. A resize
server error is tolerated only after verifying the page remains readable.

## Development

```bash
python -m pip install '.[dev]'
python -m pytest
python -m coverage run -m pytest tests
python -m coverage report --fail-under=80
# Real disposable browser + deterministic local model provider; no paid keys:
JEV_FUNCTIONAL=1 python -m pytest tests/test_functional.py -q
# Opt-in real provider smoke, costs calls and any configured proxy bandwidth:
JEV_LIVE=1 python -m pytest tests/test_live.py -s
```

CI tests installed artifacts, MCP stdio, public-image browser execution and both
old and new contracts. See [docs/testing.md](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/testing.md). Remove the demo
browser with `docker compose --env-file .env -f examples/compose.yaml down -v`.
Release history is in [CHANGELOG.md](https://github.com/harmanbassi/jev-agent-browser/blob/main/CHANGELOG.md); maintainers can use the
[release checklist](https://github.com/harmanbassi/jev-agent-browser/blob/main/docs/releasing.md) before publishing a reviewed commit.

MIT: original contributions [LICENSE](https://github.com/harmanbassi/jev-agent-browser/blob/main/LICENSE); adapted upstream portions retain
[LICENSE-jev-ultrafast](https://github.com/harmanbassi/jev-agent-browser/blob/main/LICENSE-jev-ultrafast).
