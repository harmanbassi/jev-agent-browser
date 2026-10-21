# jev_input — Camofox plugin

`POST /tabs/:tabId/jev-click {userId, x, y}`: real mouse events at viewport
coordinates, and nothing else. It replaces the core `/click`'s actionability
wait, fixed 500 ms settle and accessibility-ref rebuild (~2 s per click), which
jev-browser never uses. If the click starts a main-frame navigation within
150 ms it waits for the new document's DOM before returning.

**Opt-in: set `JEV_FAST_CLICK=1`** in the environment of whatever runs
jev-browser (your agent or MCP process). Off by default because on
2026-09-30 it lost to the core click on animated widgets: Google Flights'
trip-type menu toggled shut when the snapshot beat its opening animation, and
an earlier version returned before a navigation committed (false "done").
With it on, jev-browser falls back to the core selector click when the route
is missing (`Cannot POST`), so a Camofox without the plugin keeps working.

Measure task completion on your target sites before enabling it. Faster individual
clicks do not guarantee reliable navigation or faster complete tasks.

## Install

Camofox loads `/app/plugins/<name>/index.js` for names listed in
`/app/camofox.config.json`. Both live in the image, so mount them:

From the repository root, first copy the configuration from your built image:

```sh
docker run --rm --entrypoint cat jev-camofox:local /app/camofox.config.json > camofox.config.json
```

Enable `jev_input` under `plugins` in that local file, preserving its existing
settings. Add these mounts when starting your Camofox container:

    -v "$PWD/camofox_plugin/jev_input:/app/plugins/jev_input:ro"
    -v "$PWD/camofox.config.json:/app/camofox.config.json:ro"

with that config = the image's own plus `"jev_input": {"enabled": true}` under
`plugins`. Mounting from the checkout means the running plugin follows whatever
your checkout has checked out (pin a reviewed release), and a plugin change
needs a Camofox restart to load.

## jev_vision — masked viewport observations

The recommended Dockerfile also installs `jev_vision` and a matching copy of
`snapshot.js`. `GET /jev/vision` advertises its protocol/hash;
`POST /tabs/:tabId/jev-observation` returns a versioned, masked PNG observation
for the authenticated caller's browser identity. Both routes require browser
authentication. There is no caller-supplied script or selector. Use the built
image so plugin and Python snapshot hashes match. A custom mounted configuration
must enable `"jev_vision": {"enabled": true}` in its existing `plugins` map.
See [visual browsing](../docs/vision.md) before enabling image uploads.
