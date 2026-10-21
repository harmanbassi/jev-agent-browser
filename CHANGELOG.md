# Changelog

## Unreleased

- Ask a goal check with every decision (same request). A confident yes finishes
  only where the operation head leaves room (it gives `DONE` at least 0.15 or
  its action is below the floor), never over `NEED_GUIDANCE`/`BLOCKED`. A
  confident no overrules `DONE`, and the next-best operation is scored on its
  own probability. Results report `completion_probability` / `done_by`.
- Pool the probability of equivalent targets (same kind, role, normalized label,
  value and real `href`; never `#` or `javascript:` links) before the target
  floor, acting on the copy Jev preferred, so duplicate links no longer pause.
- Keep the strict 0.8 visual floors for `require_visual` runs only. Auto-escalated
  and `always` runs keep the text floors instead of pausing right after escalating.
- With `JEV_VISION_BOX=1`, use per-operation box answers (asked in the same request,
  with the goal and operation) to break uncertain or split target choices among
  the three most probable observed controls, instead of only ever pausing.
- Upload viewport images as baseline JPEG (quality 85) instead of PNG; pixel
  freshness checks compare the captured pixels, not the encoded upload.
- Record `from_url` and `url_after` in each step and send them with Jev's recent
  actions, so a run can tell where it has already been.
- Do not flag repeated scrolling as `no_progress` while each scroll changes the
  page; `max_steps` still bounds an endless feed.
- Report provider token usage (and cost where reported) per task in results,
  totalled and per model, for Python, CLI, MCP and Hermes.
- Supervisor fallback on the same session: MCP `browser_snapshot` / `browser_act`
  and Python `Browser.snapshot` / `Browser.act` act on observed element ids
  through the executor's freshness and target checks (click, type, select,
  allowlisted keys, scroll). Paused results name the applicable `fallback`;
  the Hermes pause guidance points to its own manual tools and continuing.
- Observations include the text of non-sensitive text areas, so code views
  (for example a hosted file's contents) reach Jev. This changes `snapshot.js`:
  rebuild the browser image so the masked-observation plugin matches.
- Browser image: bound Camofox 1.18.1's DOM-click fallback (a temporary patch
  that fails the build if the base differs), so a click on a target re-rendered
  after tagging returns 422 within seconds instead of hanging 30 s and destroying
  the tab (HTTP 410). Rebuild the browser image to apply it.
- Clients that opened their own tab reopen the last page in the same identity
  after an HTTP 410 (at most twice per task) and report `recoveries`.
- Update the browser image's MCP TypeScript SDK pin to 1.32.1 so fresh builds
  pass the current dependency security audit.

## 0.3.0 — opt-in visual browsing

- Masked, authenticated viewport observations with a versioned snapshot protocol.
- Jev 1.14 multimodal decisions through OpenRouter, independent image budgets,
  bounded image preparation and resolved-model telemetry.
- Python, CLI, MCP and native Hermes visual controls with operator opt-in,
  preserved visual requirements and fresh-image completion verification.
- Experimental presence/box cross-checking mapped only to observed DOM targets.
- Shared native-tab task serialization, safe metadata, no raw-image fallback,
  and separate free capture diagnostics / explicitly paid model probes.
- Installed-wheel real-browser pixel tests and visual guard regressions.

## 0.2.2 — release preparation

- Standalone Python client, CLI and stdio MCP interfaces alongside native Hermes.
- Isolated cookie identities for standalone sessions; bounded tasks, cancellation,
  request budgets and explicit pause/error results.
- Profile/context-scoped Hermes history, shared native browser tabs and optional
  tool-visibility compatibility patch.
- Sensitive-control redaction and guards for covered or changed targets.
- Cleanup of owned contexts after failed creation, saved-profile cleanup warnings
  and authenticated disposable diagnostics.
- Pinned Camofox 1.18.1 quickstart with dependency security updates, loopback
  binding, optional proxy and a 512 MiB Node heap budget.
- Patched minimum Requests version; pinned CI actions; installed wheel, source
  archive, MCP and real-browser regression coverage.
- Public setup, troubleshooting, operating-limit and maintainer documentation.

- Reject example credential placeholders and explain browser authentication failures.
- Pin Playwright to the version tested with the bundled Camoufox binary.
- Replace internal development templates with project testing instructions.

See [testing](TESTING.md) and the [release checklist](docs/releasing.md) for
verification. Publication and release tags are separate maintainer actions; this entry
does not imply a package has been published to PyPI.
