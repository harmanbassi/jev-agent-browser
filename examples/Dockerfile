# Keep the tested browser build and pin a compatible Playwright protocol.
ARG CAMOFOX_BASE_IMAGE=ghcr.io/jo-inc/camofox-browser:1.18.1@sha256:cff2c1432b609bde9c9d0b91e5b924dae0799d3c7bc9d468c0bc949325beaf2a
FROM ${CAMOFOX_BASE_IMAGE}
WORKDIR /app
# Patch transitive versions as well, including older operator-supplied bases.
# Ignore lifecycle scripts so the existing Firefox/native SQLite build is retained.
# A high/critical npm audit finding fails the build; NPM_AUDIT_FATAL=0 only warns.
ARG NPM_AUDIT_FATAL=1
RUN npm pkg set overrides.adm-zip=0.6.1 overrides.brace-expansion=5.0.12 \
        overrides.fast-uri=3.1.8 overrides.hono=4.13.13 overrides.ip-address=10.7.4 \
        overrides.js-yaml=4.3.2 overrides.qs=6.16.1 \
    && npm install --omit=dev --ignore-scripts --save-exact playwright-core@1.59.1 proxy-addr@2.0.8 @modelcontextprotocol/sdk@1.32.1 \
    && { npm audit --omit=dev --audit-level=high || [ "$NPM_AUDIT_FATAL" = "0" ]; } \
    && npm cache clean --force
# Temporary carry until upstream fixes /click: bounds its DOM-click fallback and
# treats a delivered click whose navigation is slow as success instead of running
# fallbacks. Fails the build if the base's code differs; see
# examples/camofox-click-timeout.mjs. Older bases can build with
# CAMOFOX_CLICK_PATCH=0, which drops both fixes: they keep the 30 s click hang
# (HTTP 410) and the slow-navigation 422s.
ARG CAMOFOX_CLICK_PATCH=1
COPY examples/camofox-click-timeout.mjs /tmp/camofox-click-timeout.mjs
RUN if [ "$CAMOFOX_CLICK_PATCH" = "1" ]; then node /tmp/camofox-click-timeout.mjs /app/server.js; fi \
    && rm /tmp/camofox-click-timeout.mjs
# Temporary carry: list a download as soon as it starts (state in_progress) instead
# of only after the whole file arrived. CAMOFOX_DOWNLOAD_PATCH=0 skips it for other
# bases; large downloads then stay invisible to the client until they finish.
ARG CAMOFOX_DOWNLOAD_PATCH=1
COPY examples/camofox-download-progress.mjs /tmp/camofox-download-progress.mjs
RUN if [ "$CAMOFOX_DOWNLOAD_PATCH" = "1" ]; then node /tmp/camofox-download-progress.mjs /app/lib/downloads.js; fi \
    && rm /tmp/camofox-download-progress.mjs
COPY camofox_plugin/jev_vision/ /app/plugins/jev_vision/
COPY jev_browser/snapshot.js /app/plugins/jev_vision/snapshot.js
RUN node -e 'const fs=require("fs");const p="/app/camofox.config.json";const c=JSON.parse(fs.readFileSync(p));if(Array.isArray(c.plugins))c.plugins.push("jev_vision");else c.plugins={...c.plugins,jev_vision:{enabled:true}};fs.writeFileSync(p,JSON.stringify(c))'
