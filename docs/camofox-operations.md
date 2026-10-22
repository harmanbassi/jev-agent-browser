# Camofox versions and operation

As checked on 2026-10-15, the latest Camofox application release is
[v1.18.1](https://github.com/jo-inc/camofox-browser/releases/tag/v1.18.1)
(`39c82094013480b373df6600d44c7f036f58356e`). The repository quickstart already
pins its multi-platform image digest. Newer `camoufox-backup-*` GitHub releases
mirror upstream browser binaries; they are not new Camofox server releases.

| Build | Verification and guidance |
| --- | --- |
| Camofox 1.18.1 plus `examples/Dockerfile` | Recommended baseline; installed-wheel execution and cleanup tested on Linux x86_64. |
| Existing Camofox 1.14.0 with a reviewed dependency layer | Tested with Camofox 1.14.0; upgrade the server after staging. |
| Other versions/platforms | Verify `doctor --probe` and browser tasks before relying on them. |

The pinned 1.18.1 container bundles Camoufox 152.0.4 beta.28 and camoufox-js
0.11.5. `examples/Dockerfile` pins Playwright Core 1.59.1, verified to resize and
execute tasks with that binary. Allowing the upstream `^1.58.0` range to select
1.62.1 caused a viewport protocol error. Browser, Playwright and camoufox-js
versions need to work together. Other images that cannot resize retain the
client's verified-geometry fallback and warning; the recommended image passes
an actual 1120×780 viewport assertion without warnings. Do not replace the
browser alone with the newest mirrored binary. The upstream application release
notes describe separate npm-install binary pins; those are not necessarily the
Docker image's binary version.

The Jev Dockerfile installs pinned JavaScript security fixes without lifecycle
scripts, preserving the base's Firefox and native SQLite build. It audits the
result and fails on remaining high/critical npm findings. If a newly published
advisory blocks a build you need, `--build-arg NPM_AUDIT_FATAL=0` prints the
audit as a warning and continues; the default (1) is unchanged. Repeat scans when
updating the base; this is not an exhaustive OS/browser security scan.

`examples/Dockerfile` also carries a temporary patch to Camofox 1.18.1's
`/click` route (`examples/camofox-click-timeout.mjs`). Its DOM-click fallback
called `locator.evaluate()` without a timeout. When a page re-renders the target
after it was tagged (a download page swapping in a platform-specific button, an
autocomplete list re-rendering), that call waited Playwright's 30-second default,
the route's whole budget, and the server destroyed the tab with HTTP 410. The
patch bounds it like the adjacent `boundingBox()` call, so the route fails within
about 12 seconds with its existing 422 and the client observes the page again;
the tab and its form state survive. The patch step fails the build if the base's
code differs, so review it whenever the base image changes and drop it once
upstream bounds that call. The same step fixes a second fallback problem: when a
click navigates to a slow page, Playwright reports the click as done and then
times out waiting for the navigation, and the route ran force, DOM and mouse
fallbacks against a page that had already gone, returning 422 after about 12
seconds for a click that worked. The patched route's click wrapper, which every
attempt goes through (the first click, forced retries and the search-results
path), instead waits, bounded inside its budget, for that navigation to commit
and reports success. To build an older
`CAMOFOX_BASE_IMAGE` whose code
differs, pass `--build-arg CAMOFOX_CLICK_PATCH=0`; that image keeps the 30-second
click hang, its HTTP 410s and the slow-navigation 422s. The client records a
click that the server abandoned after it was sent as a step with `effect`
(`taken` when the page moved, otherwise `uncertain`), so it is not lost either way.

`examples/camofox-download-progress.mjs` (build arg `CAMOFOX_DOWNLOAD_PATCH`,
default 1) makes the browser list a download as soon as it starts, with
`state: in_progress`, and update the same entry when it completes or fails. The
per-tab record cap holds from the start and never evicts a download still in
progress, and a file whose record was cleared while it arrived is deleted.
Without it, a large file is listed only once it has fully arrived, so a client
that checks right after its click sees nothing and may click again. Build an
older base with `CAMOFOX_DOWNLOAD_PATCH=0` if its download code differs; the
patch fails the build rather than guessing.

Clients that opened their own tab also recover from a 410 during a read, when no
action was in flight: they reopen the most recently observed page in the same
identity (cookies survive, the URL policy is checked again), at most twice per
task, and report `recoveries`. A 410 during an action, or during the read right
after it, pauses as `tab_lost` instead: the action may already have taken effect
(a submitted form whose response was slow), so it is never retried automatically.

## Upgrade an existing service

Record the existing image, configuration, mounts, port mappings, authentication,
proxy settings and restart policy. Back up operator-owned persisted state using
your deployment procedure. Keep secrets in private configuration.

Test the new image in a separate service with a different loopback port and
separate disposable profile storage. Reuse the proxy settings only when testing
that route intentionally; proxy traffic can be billed. Never mount live personal
profiles into a staging browser. The stock quickstart stores state only in its
container, without mounting host profiles.

Run `doctor --probe`, an interactive task and a resumed task. Verify actual tool
traces, browser identity/tab continuity where intended, cleanup and proxy exit
routing. Let active work finish before replacing the live service. Recreate it
with the recorded settings and retain a rollback image until acceptance passes.
A browser restart loses live tabs; saved cookies and open page state are separate.

Camofox 1.18 adds fixes for failed tab creation, proxy-rotation recovery and
concurrent tab cleanup. Earlier releases also stop broadcasting typed text to
plugins. These are reasons to stage an upgrade from 1.14 rather than updating
only its npm dependencies. See the upstream
[release notes](https://github.com/jo-inc/camofox-browser/releases).

## Authentication and cleanup

New services should set `CAMOFOX_ACCESS_KEY` and remain bound to loopback or
authenticated TLS/tunnels. The client sends that key as a Bearer token. For
native Hermes, set its `CAMOFOX_API_KEY` to the same value.

Existing servers may leave normal browsing routes ungated while protecting
cookie import and saved-state deletion through `CAMOFOX_API_KEY`. With no server
key, a production-mode server refuses those protected operations even if ordinary
browsing works. Configure a matching server/client key; upgrading the server
version alone does not fix this configuration gap. Coordinate key changes across
your consumers before enabling a global access key.

`doctor` checks configuration and public health; `doctor --probe` also verifies
tab creation, evaluation and owned-identity cleanup. Resolve cleanup warnings
before depending on disposable identity removal. Never disable authentication
checks or delete another user's profile to silence a warning.

The sample's Node heap budget is 512 MiB, separate from Firefox and total
container memory. Preserve this setting when recreating an existing service.
Check idle/session timeout settings as well: reaping can remove tabs while cookie
state remains saved.
