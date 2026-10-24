# FE-01 proof

Commit: see `git log task/FE-01` (SHA in final report). Branch `task/FE-01`, which includes the merge of `task/TL-01` (7217e24).

## What was built (`web/`)
- Next.js 16.4.3 (App Router), React 19, TypeScript 5 strict, Tailwind 4, shadcn config (`components.json`, `cn` helper; no shadcn primitives yet).
- `app/tokens.css`: verbatim copy of DES-01 `docs/design/tokens.css` (task/DES-01 @ d9d5747), light and dark. `app/globals.css` maps tokens to Tailwind utilities with no literals. Geist fonts are not bundled; the token font stacks fall back to system fonts until a font loader is added.
- Layout and sidebar for all 15 FR-DB-1 routes.
- BFF proxy `app/api/proxy/[...path]/route.ts`: forwards `/api/proxy/<path>` to `<origin of PAREEKSHA_API_URL>/<path>`, adds `Authorization: Bearer $PAREEKSHA_API_KEY` server-side, ignores client Authorization, drops set-cookie, rejects `..`, streams (SSE).
- Double-prefix fix: the real OpenAPI paths already start with `/api/v1`, so the proxy uses only the origin of `PAREEKSHA_API_URL` (compose value `http://api:8000/api/v1` still works). Client path `/api/v1/runs` goes to `/api/proxy/api/v1/runs` and then upstream `/api/v1/runs`.
- `proxy.ts` (Next 16 name for middleware): optional `WEB_PASSWORD` Basic gate.
- `scripts/gen-api.mjs`, openapi-fetch client, TanStack Query provider, Dockerfile, Playwright smoke.

## gen:api against the real spec
`proof/FE-01/openapi.json` is `GET /openapi.json` from the running backend (`uvicorn pareeksha.api.main:app`, TL-01 7217e24; 58 paths, 75 operations). `lib/api/schema.d.ts` (7941 lines) was generated from it; `gen-api.log` shows generate then `--check` up to date. The earlier fixture was deleted.

## Reproduce
```
cd web && npm ci
npm run lint && npm run typecheck && npm run build        # lint-typecheck-build.log
PW_CHROMIUM_PATH=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome npx playwright test   # playwright.log: 20 passed
npm run gen:api -- --from <url|file>; npm run gen:api:check -- --from <url|file>             # CI staleness gate
bash scripts/check-gate.sh                                 # gate.log: 401/401/401/200/502
```

## STUBs (R3), placeholder page bodies rendered by `RouteStub` ("This page is not implemented yet.")
Each page file starts with a `// STUB(<id>)` comment.
- STUB(FE-02): `/agents`, `/scenarios`, `/personas`, `/noise-profiles`
- STUB(FE-03): `/runs`, `/runs/new`, `/runs/compare`, and `/` Overview (AGENTS 7 names no owner for Overview; assigned to FE-03 because it needs the API-04 metrics summary)
- STUB(FE-05): `/audits`, `/dialect`, `/regression`, `/integrations`, `/dlq`, `/calibration`, `/settings/api-keys`
- Call detail `/calls/[id]` (FE-04) has no route yet and is not in the sidebar.

## Limits
- Proxy tests use a local Node server (in `tests/`) as upstream, not FastAPI.
- Dockerfile not built.
- Dark theme tokens are present but no theme switcher exists yet.
