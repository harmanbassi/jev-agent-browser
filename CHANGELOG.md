# Changelog

## Unreleased

## 0.4.0 — 2026-10-23

- Publish to PyPI from a GitHub release through trusted publishing
  (`.github/workflows/publish.yml`); the release tag must match the package
  version. README links are absolute so they work on the PyPI page.
- Bound each model reply by a 30 s wall-clock deadline and retry a stalled reply
  like a 503. The request timeout only bounded each read, so a provider keeping
  an unfinished reply alive held tasks for 5-10 minutes in live runs. A reply
  whose last bytes complete it just after the deadline is kept, not retried.
- Typed date, time, datetime-local, month, week, color and range values are
  checked against the HTML format before anything is entered: a malformed value
  ends the task with status `error` ("...: not a valid X value; nothing
  entered"). A color or range field that does not keep the exact value (a range
  clamps it) is restored and ends the same way ("...: the field did not keep the
  value; nothing applied").
- A download that fails after its click was counted as started is recorded as
  `download_failed` in that step and no longer blocks the click with
  `download_started`.
- Browser image: the download-progress patch keeps the per-tab download cap
  without evicting a download still in progress, and deletes a finished file
  whose record was cleared while it arrived instead of orphaning it.
- Browser image: `NPM_AUDIT_FATAL=0` (build arg) turns a high/critical npm audit
  finding into a warning; the default still fails the build.
- The Hermes plugin manifest version now follows the package version (it still
  said 0.2.2), checked by a test. Package metadata lists classifiers and links.
- **Rebuild the browser image.** `snapshot.js` changed, so its hash changed: clients
  of this version need the image built from it for visual observations, and older
  clients against the new image pause visual tasks with `vision_capture_failed`
  until they upgrade.
- Sensitive fields that are filled show `[filled]` (never the value) and are not
  offered to Jev for typing, so a field the supervisor filled no longer pauses
  `sensitive_action` again.
- Date, time, datetime-local, month, week, color and range inputs are observed,
  with `input_type` in the element. Date and time values are set with Playwright's
  fill (ISO format; the text helper is told the format); color and range values
  are set inside the executor's target check.
- Browser image: a click whose target the page replaced before the click was
  dispatched returns 409 `target_replaced` after the first attempt instead of
  about 12 s of fallbacks and a 422; the client treats it as not delivered.
- After an `uncertain` step, `DONE` needs the goal check at 0.9 or more;
  otherwise the task pauses with `action_uncertain` instead of reporting done.
- Browser image: downloads are listed as soon as they start (`state:
  in_progress`, separate `CAMOFOX_DOWNLOAD_PATCH` build arg), so a large download
  counts as started right after its click.
- Record a click the browser abandoned after sending it (a 409/422 from the input
  itself) as a step with `effect`: `taken` when the page moved, otherwise
  `uncertain`. Previously a click that navigated to a slow page vanished from
  history and was repeated. An identical action after an `uncertain` one with
  no page change pauses as `action_uncertain` instead of being sent twice.
- Browser image: when a click (first or forced) navigates to a slow page, the
  patched `/click` route waits (bounded) for the navigation instead of running
  fallbacks against the old page for about 12 s and returning 422. Rebuild the
  image to apply it; `CAMOFOX_CLICK_PATCH=0` drops this fix too.
- Auto-escalated and `always` vision runs finish on the text `DONE` rules; only
  `require_visual` runs need visual completion verification. That verification
  asks whether the image shows the goal's end state and passes at 0.95, or at 0.8
  with the decision's goal check at 0.9 or more.
- Wait (bounded) after clicking a control with `aria-expanded` until its state
  changes, so menus that open late (a flight search's ticket type) are observed.
- Detect clicks that start a file download (listed by the browser's downloads
  route), record the file in the step and `downloads`, and pause with
  `download_started` instead of clicking it again. A large file that is listed
  only after the click's short check is attributed before any repeat.
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
  that fails the build if the base differs; `CAMOFOX_CLICK_PATCH=0` skips it for
  older bases), so a click on a target re-rendered after tagging returns 422
  within seconds instead of hanging 30 s and destroying the tab (HTTP 410).
  Rebuild the browser image to apply it.
- After an HTTP 410 during a read, clients that opened their own tab reopen the
  latest page in the same identity (at most twice per task) and report
  `recoveries`. A 410 during or right after an action pauses as `tab_lost`
  without retrying, since the action may already have taken effect.
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
