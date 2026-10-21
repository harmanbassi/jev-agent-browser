"""jev-browser: TypeSafe's Jev decision model (via OpenRouter) driving a Camofox tab.

This directory is both the core package and the Hermes plugin. Keep module
load import-light: Hermes imports this file at discovery time, and standalone clients
import the core without Hermes on the path.
"""


def register(ctx):
    from . import hermes_tool

    ctx.register_tool(
        name="browser_task",
        toolset="browser_task",
        schema=hermes_tool.SCHEMA,
        handler=hermes_tool.handle,
        check_fn=hermes_tool.check,
        description=hermes_tool.SCHEMA["description"],
        emoji="⚡",
    )
    # Optional on older Hermes. The host owns discovery/visibility; the plugin
    # owns how its browser is used, including discovery when tools are deferred.
    register_section = getattr(ctx, "register_system_prompt_section", None)
    if callable(register_section):
        register_section(id="jev-browser.browsing", content=hermes_tool.routing_guidance,
                         max_chars=2400)
