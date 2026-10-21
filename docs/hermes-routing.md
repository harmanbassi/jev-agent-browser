# Hermes routing and acceptance tests

Jev is the interactive page executor. The supervising agent plans the work,
verifies returned page text and resolves pauses. Manual `browser_*` controls
share Hermes' current tab and remain available for screenshots and unsupported
steps. Provider errors and blocked sensitive actions must not become fabricated
successes. APIs remain appropriate when browser interaction is unnecessary.

## Tool visibility and instructions

With plugin prompt-section support, enabling `jev_browser` adds profile-gated
Jev-first instructions automatically. They also explain how to discover and
invoke `browser_task` through Hermes' tool-search bridge when it is deferred.
An older Hermes without this API can use the guidance in
`jev_browser.hermes_tool.BROWSING_INSTRUCTIONS` in its own agent instructions.
No global tool registry, core allowlist or installed computer-use skill is
modified by the plugin.

Hermes v0.21.6 normally defers plugin tools even when their toolset is enabled.
This repository includes an **optional compatibility patch**, tested against
Hermes v0.21.6 (`818c13be1dc4fd28987e1e881a9408224afd4535`) and a deployment
based on that version. It adds `tools.tool_search.keep`, an exact-name list of
already-enabled tools that remain directly visible. Other plugin/MCP tools keep
their normal deferral behavior. A pin cannot enable an unavailable tool or grant
access across profiles. `keep` takes precedence over `defer` for the same name.
This setting is supplied by the patch; it is not a stock v0.21.6 setting.

Apply only to a compatible Hermes source checkout you administer. Review the
patch and back up your configuration first. Git's check must succeed; if your
version differs, stop and adapt the patch rather than forcing it:

```bash
git -C /path/to/hermes-agent apply --check /path/to/jev-agent-browser/integrations/hermes/tool-search-keep.patch
git -C /path/to/hermes-agent apply /path/to/jev-agent-browser/integrations/hermes/tool-search-keep.patch
```

Merge into each participating profile's `config.yaml`, alongside the plugin,
`browser_task` toolset and Camofox selection from the README:

```yaml
tools:
  tool_search:
    keep: [browser_task]
```

Restart Hermes after code changes, with active work allowed to finish first.
Verify both a fresh session and an existing conversation: configuration changes
may rebuild tool schemas, while plugin prompt sections are frozen when a session
prompt is built. No proxy change is involved. Follow your deployment procedure
to reapply the patch after a Hermes upgrade, or remove the pin when using an
unpatched host. The plugin's discovery guidance works without the patch.

Hermes can also persist the full system prompt and tool-schema array across
process restarts. After an upgrade, use a new session or the host's supported
prompt/tool-cache refresh procedure and verify the actual schema sent on the
next turn. Preserve conversation messages when refreshing an existing session.
Restarting a process alone may restore the previous cached prompt and schemas.

## Acceptance: normal user requests, actual tool traces

In a new chat, ask:

> Browse IKEA's UK website and find three desks under £200, between 100 and
> 140 cm wide. Use the site's filters, check the product pages, recommend one,
> and send a screenshot. Don't sign in or buy anything.

Then:

> Actually, I need drawers too. Can you find a better option within the same budget?

Pass evidence is a real `browser_task` call (direct or through `tool_call`), its
returned status, matching browser-side tab/identity activity, and page evidence
for the recommendation. A screenshot-only call or a manual click loop does not
prove Jev was used. Verify continued browser identity on the follow-up. With native tab adoption
enabled, verify that the initial call without a URL reuses the existing tab;
reopening the URL after a missing-page error does not prove tab continuity. Retailer availability, CAPTCHAs and model judgments
can vary: record an honest pause/error, not an unconditional success expectation.
Do not use a real user's authenticated cookie identity for automated smoke tests.

The IKEA acceptance run exposed covered product links beneath a cookie banner:
the snapshot offered those links even though the executor correctly refused
their clicks. Snapshots now apply the executor's center-point hit test before
offering a target. The installed-wheel browser regression checks both banner
dismissal and refusal when a new overlay covers a previously observed target.

For host-patch regressions, run its added tests and Hermes' existing tool-search
suite in Hermes' Python environment:

```bash
python -m pytest tests/tools/test_tool_search_keep.py tests/tools/test_tool_search.py -q
```

The repository's offline suite checks plugin registration and profile-gated
instructions. Standalone wheel/MCP/direct-browser tests remain independent of
Hermes. Live Jev/proxy calls are opt-in and consume provider credits/bandwidth.
