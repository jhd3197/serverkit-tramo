# serverkit-tramo

Node-based automation builder for [ServerKit](https://github.com/jhd3197/ServerKit),
powered by [tramo](https://github.com/jhd3197/tramo). Design workflows on a
visual canvas (triggers, actions, branches, loops, approval gates) that react
to panel events or run on a schedule, with 21 brand integration packs
(Telegram, GitHub, Gmail, Discord, Notion, Stripe, Cloudflare, Postgres,
Twilio and more). Enabled workflows deploy to a managed tramo container on the
panel host that runs them headless, with run history, approvals, and inbound
webhooks proxied through the panel. Adds an **Automations** page
(`/automations`) plus a full-bleed editor (`/automations/edit/:slug`).

Installs from the ServerKit Marketplace (registry:
[serverkit-extensions](https://github.com/jhd3197/serverkit-extensions)).

## Repository layout

```
plugin.json               # extension manifest (routes, nav, jobs, SDK + panel gates)
backend/                  # Flask blueprint + host service, workflow store, jobs, models
frontend/                 # runtime-ESM bundle source (vite lib build)
  runtime-entry.jsx       #   entry: injects inline CSS, exports the route components
  components/             #   AutomationsPage, AutomationEditorPage, TramoEditor +
                          #   local Button/Input/Label/Modal/ConfirmDialog/EmptyState stand-ins
  registry.js             #   tramo node registry (builtin pack + 21 brand packs)
  styles/tramo-automations.scss  # page styles (host CSS custom properties)
scripts/build-zip.*       # release packaging (dist/serverkit-tramo-<version>.zip)
tests/                    # backend tests (run from a panel checkout — see tests/README.md)
```

## Development

The frontend is a **runtime-ESM extension**: it builds to a single
`frontend/dist/index.mjs` that the panel blob-imports at runtime — no panel
rebuild needed. React, react-router and `serverkit-sdk` are externalized and
resolved to the panel's own singletons via its import map; everything else
(the `tramo` editor + integration packs, lucide-react icons) is bundled, and
all CSS (the page SCSS and tramo's own canvas styles) is inlined into the
bundle.

```bash
cd frontend
npm install
npm run build        # writes frontend/dist/index.mjs
```

Load it into a dev panel with **Marketplace → Plugins → Upload Zip**, or:

```bash
./scripts/build-zip.sh    # or scripts/build-zip.ps1 on Windows
# → dist/serverkit-tramo-<version>.zip
```

For API details and the contribution model see
[docs/EXTENSIONS.md](https://github.com/jhd3197/ServerKit/blob/main/docs/EXTENSIONS.md)
in the main repo.

## Release

Fully automated — no manual zips:

1. Bump `version` in `plugin.json` and push to `main` (or push a `vX.Y.Z` tag).
2. The **Create Release** workflow builds the bundle, zips it, creates the
   GitHub release with the zip attached, then downloads the published asset
   and upserts this extension's entry (version, URL, sha256) in
   [serverkit-extensions](https://github.com/jhd3197/serverkit-extensions).

One-time setup: add a `REGISTRY_TOKEN` secret (fine-grained PAT with
contents:write on `serverkit-extensions`) so the registry sync can push.
Without it the release still ships; only the registry update skips.

## License

MIT — see [LICENSE](LICENSE).
