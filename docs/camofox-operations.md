# Camofox versions and operation

As checked on 2026-10-15, the latest Camofox application release is
[v1.18.1](https://github.com/jo-inc/camofox-browser/releases/tag/v1.18.1)
(`39c82094013480b373df6600d44c7f036f58356e`). The repository quickstart already
pins its multi-platform image digest. Newer `camoufox-backup-*` GitHub releases
mirror upstream browser binaries; they are not new Camofox server releases.

| Build | Verification and guidance |
| --- | --- |
| Camofox 1.18.1 plus `examples/Dockerfile` | Recommended baseline; installed-wheel execution and cleanup tested on Linux x86_64. |
| Existing Camofox 1.14.0 with a reviewed dependency layer | Tested deployment compatibility; upgrade the server after staging. |
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
result and fails on remaining high/critical npm findings. Repeat scans when
updating the base; this is not an exhaustive OS/browser security scan.

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
