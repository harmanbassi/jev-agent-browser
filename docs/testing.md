# Release verification

Run the commands in [TESTING.md](../TESTING.md) for each change. CI tests the full
tree on Python 3.11 and 3.14 with an 80% overall coverage threshold, builds both
distribution formats, and runs a real browser. No private development hooks,
task tracker or external gate scripts are required.

`tests/test_distribution.py` builds a wheel from tracked source, installs into a
temporary target and imports it outside the checkout without Hermes. Package
assets and upstream licensing are checked. The normal suite also performs an
actual MCP stdio initialization/tool exchange and thread cancellation tests.

`JEV_FUNCTIONAL=1 python -m pytest tests/test_functional.py -q` requires Linux,
Docker Engine, host networking, and access to the pinned public image.
It builds `examples/Dockerfile`, including an npm audit of the patched runtime
dependencies, then starts its own authenticated Camofox container on a dynamic loopback port,
with no production mounts and no proxy. A local deterministic provider replaces
Jev/text API calls; the real browser still observes, fills, clicks, checks stale
state and reaches the final page. The **installed wheel** executes the task.
The fixture records HTTP 500s, uncaught page errors, unhandled rejections and
console.error. Teardown stops the HTTP server and removes the container/volumes.
The built image is removed at teardown. The downloaded base image can be removed
separately if no longer needed. `JEV_TEST_CAMOFOX_BASE_IMAGE` can select an
operator's existing browser image for an additional compatibility run.

The Dockerfile pins fixes for the upstream JavaScript dependency alerts found
during the release audit and fails its build if the runtime npm audit still has
high or critical findings. It does not run dependency lifecycle scripts or
replace Firefox/native SQLite. This scans npm dependencies, not every OS or
browser vulnerability; repeat broader image scans when updating the base.

Parity gaps: the deterministic provider proves the transport/executor, not real
Jev judgments. The public pinned browser is tested directly; a private metered
proxy and the deployed Hermes installation cannot run in public CI. Verify
those with isolated identities against the existing service before deployment.
Never use a real user's cookie identity for a smoke test.

`JEV_LIVE=1 python -m pytest tests/test_live.py -s` uses the configured real
OpenRouter key and Camofox service, consumes paid calls/proxy bandwidth, and must
stay opt-in. Set its environment through your secret manager; do not paste keys
into reports. A successful smoke does not guarantee every website works.

For a paid paired visual evaluation on disposable identities, explicitly export
`JEV_VISION_ENABLED=1` and run:

```sh
JEV_LIVE_VISION=1 python -m pytest tests/test_live_vision.py -q -o junit_family=xunit1 --junitxml=vision-evaluation.xml
```

This compares two button layouts across `off`, `auto` with a required visual goal,
and `always`. Image modes must never execute a wrong target or falsely report completion.
Safe pauses are recorded separately; a green run is a safety result, not a claim
of 100% model completion. The text baseline records its outcome without pretending equal DOM labels reveal color.
The JUnit property records status, correctness, elapsed time, model IDs and visual
request/capture counts, never images. Run once against a direct browser, and again
against a separately configured proxied browser when maintaining such a setup.
No key, identity, proxy provider or host-specific path is embedded in the tests.
