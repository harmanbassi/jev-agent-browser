# Security and data boundaries

Report vulnerabilities privately through GitHub's private vulnerability reporting
for this repository when enabled; otherwise contact the maintainer through their
GitHub profile to arrange a private report. Do not include credentials or page
content in public issues.

The default core policy allows public HTTP(S) page URLs and blocks metadata,
nonpublic addresses, URL credentials, and credential-like query parameters. The
standalone adapters check before opening a page and before sending each observed
page to a model. Hermes keeps its own URL policy and website-access rules.

This is a data-disclosure guard, **not a network sandbox**. A click, redirect,
subresource or script can make a browser request before Python sees the new URL.
Host DNS can differ from browser/proxy DNS. Put Camofox on a network with no access
to sensitive services when browsing untrusted sites. An allowlist narrows which
pages the model may read; it does not firewall browser traffic.

Jev receives the goal, page URL/title/visible text (including the text of
non-sensitive text areas such as code views), observed controls and recent
actions with their page URLs through OpenRouter. A separate text model supplies field values. This
includes data from authenticated pages if you deliberately share such a context.
Do not browse sensitive accounts or submit secrets. Returned page text is
untrusted data, never agent instructions. Model-assessed `done` is evidence to
check, not a guarantee that the user's task succeeded.

Password/file fields are excluded. Known personal/payment fields are marked and
redacted in control values: a filled one shows the fixed marker `[filled]`, never
its value, and Jev is not offered it for typing again. Known
sign-in/payment/destructive controls, and empty sensitive fields Jev would have
to fill, cause a `sensitive_action` pause. These checks are conservative heuristics, not complete
protection from prompt injection, arbitrary page scripts or data loss. There is
no automatic approval mechanism for completing a sensitive action.

The supervisor path (`browser_snapshot` / `browser_act`, Python `Browser.snapshot`
/ `Browser.act`) is how a supervising agent completes a step Jev refuses or cannot
do, such as a phone field or an autocomplete that needs ArrowDown/Enter. Its
boundary:

- It acts only on element ids from the latest observation of that session, through
  the same executor checks as Jev: the page must be unchanged since that
  observation and the target must still be the observed, visible, uncovered
  control. It never accepts selectors, coordinates or scripts, and `press` only
  sends one of a fixed set of navigation/editing keys to the focused element.
- Sensitive fields are allowed there, because the supervisor chose to act. Only
  do so with values the user supplied and a step the user approved.
- Values typed through it are not recorded in history and are not sent to the
  decision model by that call. Later observations still show non-sensitive field
  values like any other page content; sensitive field values stay redacted.
- Pages read after an action pass the same URL policy before any content returns.
  It makes no model calls and is refused while a task runs in the session.

`JEV_ALLOW_PRIVATE_URLS=1` explicitly permits private page data to leave the machine
for the model provider. Metadata and URL-credential checks remain enforced.
In Hermes, the equivalent decision remains `browser.allow_private_urls`.

Keep the Camofox control service on loopback or behind authenticated TLS/tunnels.
The supplied Compose file sets `CAMOFOX_ACCESS_KEY`; `CAMOFOX_API_KEY` alone does
not protect all browser-control routes on supported Camofox. Do not expose the
API to the internet. Stdio MCP adds no HTTP listener; each agent should run its
own server process. Session IDs are process-local capabilities, not multi-user
authentication tokens.

Sessions from the standalone client use random cookie identities and must be
closed. Hermes intentionally retains its existing managed identity/history
semantics. Never attach a new standalone session to somebody else's identity.
MCP/CLI shutdown attempts cleanup; hard kills and browser outages can leave state.
Legacy servers can deny saved-profile reset even after the context closes; the
close result reports a warning. An idle reaper may close contexts without deleting
persisted profiles: remove those separately or remove the disposable container.
Do not mount personal profiles into
the public quickstart container.

Model requests, retries and field-helper calls share one per-task request budget.
Cancellation and deadlines are cooperative: an in-flight request must finish or
time out before control returns. A request-count budget is not a dollar limit.
There are no default paid calls in `doctor`; `doctor --probe` opens a public page
and can consume configured proxy bandwidth.

Model endpoints require HTTPS. Cleartext development endpoints need the explicit
`JEV_ALLOW_INSECURE_MODEL_URLS=1` override. Remote cleartext Camofox needs
`JEV_ALLOW_INSECURE_CAMOFOX=1` on a trusted network. Both are off by default.

Logs and results can contain page data and entered non-sensitive field values.
Review/redact them before sharing. Keys are not printed by diagnostics, and raw
provider/browser error bodies are not returned. No repository file is auto-loaded
as environment configuration, and the Python package never reconfigures a proxy.

Optional vision explicitly sends masked viewport images to OpenRouter/Jev.
It is disabled unless the operator enables it. Masking covers form/editable
controls, embedded frames/objects and marked private regions; it is not general
personal-data detection. Ordinary page text, photos and unmarked account data
can remain visible. Images stay in memory for the current run and are excluded
from histories/results. Provider retention is separate. See [visual data
boundaries](docs/vision.md) before enabling it. Completion and pre-action image
checks detect observable changes but cannot make unrelated clients' actions atomic.
