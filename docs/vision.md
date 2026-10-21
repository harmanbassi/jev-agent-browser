# Visual browsing (experimental)

Jev 1.14 accepts images through OpenRouter Decisions using your existing
OpenRouter key. No TypeSafe key or direct-API danger-zone header is needed for
this route. Access depends on your provider account; use the explicit paid
model probe to verify it. Image calls can cost more and take longer than text
calls. This feature does not provide unrestricted computer use.

## Install and configure

Install `.[vision]` for Python/CLI or `.[mcp,vision]` for an MCP client, then
rebuild/recreate the Camofox container using `examples/Dockerfile`. The image
includes the authenticated `jev_vision` plugin and matching snapshot code.
If you mount a custom Camofox configuration, enable `jev_vision` in its `plugins`
map while preserving your other settings. Do not mount an older plugin over
the image copy. No proxy is needed; an existing browser-side proxy continues
working without changing model requests or host networking.

Set these in your process's secret/config injection or active Hermes profile:

| Setting | Default | Meaning |
| --- | --- | --- |
| `JEV_VISION_ENABLED` | `0` | Operator permission for image uploads |
| `JEV_VISION_MODE` | `auto` | `off`, `auto`, `always` |
| `JEV_VISION_MODEL` | `typesafe/jev-1.14` | Tested image model; independently pinned |
| `JEV_VISION_MAX_CALLS` | `4` | Image HTTP attempts per task (1–32) |
| `JEV_VISION_BOX` | `0` | Experimental presence + box cross-check |

Forward all five variables in MCP clients that filter inherited environment
variables. Codex's example in the README includes them. Claude Code inherits
its configured server environment. Hermes reads the active profile's scoped
settings, without borrowing vision permission from another profile.

Run `jev-browser doctor --vision` for a free capability and masked-capture check.
Run `jev-browser doctor --vision-model-probe` to explicitly upload a throwaway
example.com image and make a paid provider request. Both clean up their own tab.

## Task controls

Use `require_visual=true` for images, appearance, colors or layout. This starts
visual reasoning immediately and refuses a DOM-only completion. In `auto`,
ordinary text tasks escalate once on uncertain/blocked/no-progress decisions.
After escalation, images remain required for the rest of that run. Only
`require_visual` runs use the strict 0.8 operation/target confidence floors;
escalated and `always` runs keep the text floors (0.35 operation, 0.2 target)
and still need visual completion verification. The one escalation is reported
as `vision.escalations`.
`vision=always` starts visually; `vision=off` disables images for that task.
An agent cannot grant itself operator permission.

A visual requirement survives subsequent calls on the same standalone session
or native Hermes task/tab. Omit the option to preserve it; explicitly pass
`require_visual=false` to clear it when the user's goal changes. A new Hermes
URL resets that task's continuation history and visual requirement. Other task
IDs do not share histories, even when they adopt the same native tab. Native
Jev tasks in one profile are serialized before navigation; manual browser tools
can still change the tab, which freshness checks detect where observable.

The image budget counts retries and the separate completion verification.
The overall model budget also counts every image request and any text helper
requests. Captures have a separate bound of three times the image-attempt
budget. Deadlines and cancellation are checked before captures, streamed reads,
provider attempts and actions. A budget pause can be resumed with a new budget;
images themselves are never carried into the next call.

## Privacy and execution boundaries

Only an authenticated, version-matched plugin can supply images. It captures
one viewport in memory and masks inputs, textareas, selects, editable regions,
iframes, embedded objects and `[data-jev-private]` regions in black. Model-facing
text excludes these regions and editable values. Non-sensitive dropdown choices
remain available as structured DOM options. Sensitive controls remain blocked
by the existing executor policy. There is no raw screenshot fallback.

Masking is not general-purpose personal-data detection: ordinary page text,
photos, account names, URLs and other unmarked content can still appear in an
image. Only enable this for pages you permit the provider to see. Page content
remains untrusted. Masked evidence cannot prove a requirement inside a masked
region. URL policy is checked before capture/upload, including redirects.

Images are validated, bounded, resized to the model's limits and kept only for
the current run. Results contain counts and resolved model IDs, never image
bytes. Jev does not save screenshots, cache them across profiles or put them in
histories. The upstream provider's retention policy is separate.

The model chooses only from observed DOM actions. Before a visual action, a fresh
masked capture must match the selected target's pixels and DOM fingerprint.
Completion requires a fresh image, an affirmative Noul answer, and another
capture that confirms the evidence has not changed during verification. These
checks are conservative: video, animation and changing ads can cause safe pauses.
They cannot make concurrent changes from unrelated clients atomic.

Optional Box output is accepted only with positive presence evidence and a
unique mapping to the already selected DOM target. No model-produced box,
coordinate, selector or script is executed. Canvas-only and unsupported iframe
controls still require a supervising agent's manual tools.

## Common pauses

- `vision_disabled`: operator permission or mode forbids the requested evidence.
- `vision_dependency_missing`: install the vision extra in the executing interpreter.
- `vision_capture_unavailable`: rebuild/enable the matching browser plugin.
- `vision_capture_failed` / `vision_invalid_observation`: capture or protocol validation failed.
- `vision_budget` / `vision_capture_budget`: resume with an appropriate fresh budget.
- `vision_completion_unverified`: the image did not establish every requirement.
- `vision_target_ambiguous`: optional box/presence evidence could not identify one target.
- `low_confidence`: operation/target confidence is below the floor (0.8 for `require_visual` runs).

Do not remove a visual requirement merely to get a successful status. Inspect
returned evidence and explain limitations to the user.
