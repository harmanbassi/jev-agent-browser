# Contributing

Use Python 3.11 or newer and a virtual environment:

```sh
python -m pip install '.[dev]'
python -m coverage run -m pytest tests
python -m coverage report --fail-under=80
python -m build
```

With Linux and Docker, also run the installed-package browser tests:

```sh
JEV_FUNCTIONAL=1 python -m pytest tests/test_functional.py -q
```

These start a disposable browser without a proxy and use a local model fixture.
No paid key is required. Live model/proxy tests are explicitly opt-in; see
[docs/testing.md](docs/testing.md). Do not mount personal profiles into tests.
CI checks Python 3.11 and 3.14, packaging, browser execution, and secrets in Git
history. [TESTING.md](TESTING.md) lists the commands contributors can run locally.

Keep core imports independent of Hermes. Changes to observations, targeting,
budgets, cleanup or profile handling need behavior regressions in the existing
pytest suite. Include real browser regressions when DOM behavior changes.
Model output must never become an arbitrary selector, coordinate or script.
Preserve upstream attribution when adapting code.

Open a pull request with the problem, resulting behavior and validation. Never
include API/proxy keys, cookies, private page content or captured user sessions.
Report security issues privately as described in [SECURITY.md](SECURITY.md).
