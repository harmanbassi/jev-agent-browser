# Changelog

## Unreleased

- Ask a goal check with every decision (same request): finish on a confident yes,
  overrule an unsupported `DONE` on a confident no, and report
  `completion_probability` / `done_by` in results.
- Pool the probability of equivalent targets (same kind, role, normalized label,
  value and `href`) before the target floor, so duplicate links no longer pause.
- Keep the strict 0.8 visual floors for `require_visual` runs only. Auto-escalated
  and `always` runs keep the text floors instead of pausing right after escalating.
- With `JEV_VISION_BOX=1`, use per-operation box answers (asked in the same request,
  with the goal and operation) to break uncertain or split target choices among
  the three most probable observed controls, instead of only ever pausing.
- Upload viewport images as baseline JPEG (quality 85) instead of PNG; pixel
  freshness checks compare the captured pixels, not the encoded upload.
- Record the page URL in each step and send it with Jev's recent actions, so a
  run can tell it already visited a page instead of navigating back and forth.
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
