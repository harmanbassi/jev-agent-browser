# Troubleshooting

Run `jev-browser doctor`, then `jev-browser doctor --probe`. Neither makes a paid
model call; the probe opens example.com and can consume proxy bandwidth. Do not
paste credentials, private page data or complete session logs into public issues.

| Symptom | What to check |
| --- | --- |
| Tool missing in Codex/Claude | Install the MCP extra, register the absolute executable path and restart/reconnect the client. Verify active tools, not only installed packages. |
| Tool exists but reports no model key | Export a key before launching the agent or configure secret injection. Codex must forward the variable name through `env_vars`. Files in the cwd are never auto-loaded. |
| Example key rejected | Replace every `replace-with-...` value from `.env.example`. Use an actual OpenRouter key and a separately generated browser key shared by server and clients. Diagnostics do not verify provider access without a model call. |
| MCP call times out | Set the client tool timeout above the task timeout. A client disconnect does not necessarily interrupt an in-flight browser/model request immediately. |
| Health succeeds but browsing fails with 401/403 | `/health` is public on supported Camofox. Run the probe and check the server/client browser keys. Provider 401/403 is separate: verify the OpenRouter key and Jev endpoint access. |
| Saved-profile reset warning | The context closed, but the server refused removal of saved state. Configure matching authentication as described in [Camofox operations](camofox-operations.md), then clean only owned identities through the supported API. |
| CLI follow-up has no previous page | Each `run` command closes its identity. Use MCP or Python for a persistent multi-call session. |
| Hermes follow-up has no page | Verify Camofox selection and optional managed-persistence/tab-adoption settings. A server restart or reaper can still remove tabs. See [Hermes routing](hermes-routing.md). |
| Private site blocked | Standalone access requires explicit `JEV_ALLOW_PRIVATE_URLS=1`; this authorizes sending private page data to the provider. Hermes uses its own URL/website policy. Metadata and URL credentials remain blocked. |
| Local site unreachable | Use a separate direct browser for local sites. An existing residential proxy may not be able to reach your LAN or container host. |
| Wrong Camofox service reached | If changing Compose's `CAMOFOX_PORT`, set `CAMOFOX_URL` to the same host port and restart the MCP process. Avoid accidentally testing an existing proxied browser. |
| Resize warning | Some browser/library combinations cannot resize. The client uses verified current geometry. Persistent unreadable-page errors require a compatible Camofox/browser build. |
| Click errors with HTTP 410 / `recoveries` in results | The browser destroyed a tab whose operation hung (Camofox 1.18.1 waits 30 s in a click fallback when a re-render hides the target). Rebuild from `examples/Dockerfile`, which bounds that call so the click fails fast and Jev observes again. Clients that opened their own tab reopen the latest page in the same identity after a lost read (at most twice per task); a tab lost during an action pauses as `tab_lost`, because the action may already have taken effect. Check before repeating it. |
| `download_started` pause | A click started a file download instead of opening a page. Jev does not repeat it; `downloads` names the file. Rephrase the goal if the file was not wanted. |
| `paused` result | Inspect `reason`, `fallback` and page evidence. Clarify or split the goal, or do the step with `browser_snapshot`/`browser_act`, then continue the same session. Do not loop on `sensitive_action`. |
| `done` with an incomplete task | Check all requirements against visible evidence. Give a bounded corrective goal using the same session; report uncertainty rather than treating `done` as proof. |

For a useful bug report, include the Jev commit/version, Python/OS/architecture,
Camofox image digest and browser/library versions, interface used, redacted
status/reason and a public reproducible page. State whether a proxy was enabled
without supplying its credentials or personal exit address.
