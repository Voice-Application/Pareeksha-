# FE-01 proof

Commit: see `git log task/FE-01` (SHA in final report). Branch `task/FE-01`.

## What was built (`web/`)
- Next.js 16.4.3 (App Router) + React 19 + TypeScript strict + Tailwind 4 + shadcn config (`components.json`, `lib/utils.ts` cn helper; no shadcn primitives installed yet, FE-02 adds them once DES-01 tokens exist).
- `app/tokens.css`: the only place for colour/type/spacing/radius values. All values are neutral PLACEHOLDERS marked for replacement by DES-01. `app/globals.css` maps them to Tailwind via `@theme inline` (no literals).
- Layout + sidebar (`components/layout/sidebar.tsx`, `lib/nav.ts`) listing every FR-DB-1 route; each route has a plain page via `RouteStub` ("This page is not implemented yet."), implemented by later FE tasks.
- BFF proxy `app/api/proxy/[...path]/route.ts`: forwards to `PAREEKSHA_API_URL`, adds `Authorization: Bearer $PAREEKSHA_API_KEY` server-side, ignores client Authorization/cookies, drops upstream set-cookie, rejects `..` segments, streams body (SSE).
- `proxy.ts` (Next 16 name for middleware): optional `WEB_PASSWORD` Basic-auth gate.
- `scripts/gen-api.mjs` (`npm run gen:api`, `gen:api:check`), `lib/api/client.ts` (openapi-fetch), TanStack Query provider, Dockerfile, `.env.example`, Playwright smoke test.

## Reproduce
```
cd web && npm ci
npm run lint && npm run typecheck && npm run build
PW_CHROMIUM_PATH=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome npx playwright test
bash scripts/check-gen-api.sh      # gen:api + staleness gate
npm run build && bash scripts/check-gate.sh   # WEB_PASSWORD gate
```
Expected: lint/typecheck/build exit 0; Playwright `20 passed`; gate log 401/401/401/200/502; gen-api log fresh=0, stale=1, regenerated=0, unreachable=1.

## Evidence (this directory)
`lint.log`, `typecheck.log`, `build.log` (17 routes incl. dynamic proxy), `playwright.log` (20/20), `gate.log`, `gen-api.log`.

## Limits / blocked parts
- BLOCKED on TL-01: `gen:api` "against TL-01's OpenAPI". The script works (proved on a fixture: `web/tests/fixtures/openapi.health.json`, hand-written from `docs/06-api-spec.md` `/health`), but the committed `lib/api/schema.d.ts` is generated from that fixture only. After TL-01: run `npm run gen:api` against the real `/openapi.json` and commit.
- Proxy tests use a local Node HTTP server (in `tests/`) as the upstream, not the real FastAPI.
- Docker image build not run (Dockerfile unverified).
- Visual design intentionally absent; waits for DES-01.
