# Testing jev-browser

Use Python 3.11 or newer in a virtual environment:

```sh
python -m pip install '.[dev]'
python -m coverage run -m pytest tests
python -m coverage report --fail-under=80
python -m build
```

The default suite uses fake model/browser responses and makes no paid model
calls. It tests the executor, data guards, session isolation, budgets, native
Hermes adapter, MCP stdio and installed distributions. Docker and paid-provider
tests are skipped unless explicitly enabled.

On Linux with Docker Engine, run the real browser acceptance tests:

```sh
JEV_FUNCTIONAL=1 python -m pytest tests/test_functional.py -q
```

These build the same pinned image as the quickstart, install a wheel outside the
checkout, and exercise authenticated browsing with a local deterministic model
provider. They use disposable containers and identities, no proxy and no personal
profiles. They verify form entry/submission, viewport compatibility, target guards,
authentication diagnostics and cleanup; page errors and server failures fail the
tests. Containers and generated images are removed on teardown.

CI runs Python 3.11 and 3.14, requires 80% overall coverage, builds artifacts,
runs the real browser tests, and scans Git history for secrets.

See [docs/testing.md](docs/testing.md) for test boundaries and optional live
provider verification. A working deterministic provider does not establish
Jev's judgment on every website.

Visual tests cover masked pixel capture, safe metadata, protocol/version checks,
image dimensions and transforms, image-attempt and capture budgets, stale target
pixels, completion verification, profile opt-in and continuation requirements.
The real-browser fixture chooses between equally labelled controls by reading
screenshot pixels and checks a colored completion banner. It makes no paid calls.
For real-provider testing use `doctor --vision-model-probe` explicitly; local
fixture success alone does not establish the model's visual judgment.
