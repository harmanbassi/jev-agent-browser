# Connecting an agent

The supervising agent sets goals, verifies page evidence and handles pauses.
Jev chooses from observed page actions; Camofox executes them. Supply your own
OpenRouter key for Jev and its field-text model. Those calls have their own
provider costs, separate from your supervising agent's subscription.

| Interface | Session behavior | Intended use |
| --- | --- | --- |
| CLI `jev-browser run` | Opens an isolated identity and closes it when the command exits. | One task from any agent with shell access. |
| MCP | `browser_open` returns a process-local session ID; subsequent tasks can resume it. | Codex, Claude Code and other MCP clients. |
| Python `Browser` | Same owned-session model as MCP; close explicitly or use a context manager. | Custom agents and integrations. |
| Native Hermes plugin | Uses Hermes' own tab, auth, identity and website policy. | Coordinated `browser_task` and `browser_*` use inside Hermes. |

Standalone sessions are independent of native Hermes sessions even when they
use the same Camofox server or proxy. The MCP `browser_task` requires a session
ID; the native Hermes tool instead uses its current task's tab.

The MCP server exports seven tools: `browser_open`, `browser_task`,
`browser_snapshot`, `browser_act`, `browser_inspect`, `browser_cancel` and
`browser_close`. Results contain page text and status. When a task pauses, the
supervisor can do one step itself on the same tab: `browser_snapshot` returns the
page text and element ids, `browser_act` clicks, types, selects, presses an
allowlisted key or scrolls on those ids, and `browser_task` then continues the
same session. Screenshots require a separate host integration; Hermes'
`browser_*` tools are not automatically present in standalone MCP clients.
Another browser tool does not automatically share a standalone session's cookies
or tab.

## Codex and Claude Code

First complete the [README quickstart](../README.md) and make `doctor --probe`
pass. Install the `mcp` extra from your source checkout. Export the credentials
and browser URL before starting your agent, or use its secret injection.
Keep credential values out of checked-in configuration.

Use the executable's absolute path in the client configuration from the README.
For Codex, configure `[mcp_servers.jev-browser]`, forward the needed variable
names using `env_vars`, and set `tool_timeout_sec` above the task deadline.
Extend that allowlist for any additional optional settings you use. Check with
`codex mcp list` and the active session's `/mcp` view after restarting/reconnecting.
For Claude Code, register the stdio command with `claude mcp add` as shown in the
README and check its active MCP tools. Consult the clients' official
[Codex](https://developers.openai.com/codex/mcp) and
[Claude Code](https://code.claude.com/docs/en/mcp) instructions for your version.

Close sessions explicitly before quitting the client. Clients can force-stop a
stdio process before shutdown cleanup finishes; Claude Code documents a short
shutdown grace period. Lifespan cleanup is a fallback, not a replacement for a
successful `browser_close` result.

Registration is distinct from tool selection. An agent may prefer search or
manual browsing unless its instructions establish when to use Jev. Add guidance
like this to your own agent/project instructions if Jev should be the default:

> Use the Jev MCP tools first for interactive web browsing. Open a session, give
> browser_task a concrete goal and required values, and verify its returned page
> evidence. Continue using the same session ID for follow-ups. Resolve pauses
> with a clearer goal or an allowed manual fallback; never retry to bypass a
> sensitive-action or URL block. Prefer documented APIs for tasks requiring no
> browser interaction. Close sessions when finished.

Tool names may have a client-specific server prefix. Verify a real tool call in
the trace; an agent saying it used Jev is insufficient evidence.

## A normal task and follow-up

Ask the agent to browse a public site and perform a small interaction, for example:

> Find Python's Wikipedia article, open it and tell me who designed the language.

Then ask:

> On that same page, find the first release date.

For MCP, inspect the trace for `browser_open`, actual `browser_task` results,
the same session ID on the follow-up, and eventual `browser_close`. Check the
returned page evidence yourself. A `paused` result is a handoff to the supervisor;
`done` is the model's assessment, not an independent correctness guarantee.

For native Hermes setup, routing and tab-continuity acceptance, use
[hermes-routing.md](hermes-routing.md).
