# Jev Agent Browser contributor guidance

Jev chooses actions on observed page controls; Camofox executes them. The core
supports Python, CLI and MCP, with an optional native Hermes plugin.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [TESTING.md](TESTING.md) before changes.
Work on a branch and open a pull request.

- Keep `__init__.py` import-light. Only `hermes_tool.py` may import Hermes
  modules; the core must install and run without Hermes.
- Model output must never become an arbitrary selector, coordinate or script.
  Preserve observation freshness checks and executor-owned target validation.
- Preserve profile isolation, URL/data policies, budgets and owned-session cleanup.
- Use the existing pytest fixtures and include behavior regressions for fixes.
- Keep upstream attribution in adapted modules and `LICENSE-jev-ultrafast`.
- Never commit credentials, personal profiles, private deployment details or
  local agent policies. Release preparation does not authorize publication.
