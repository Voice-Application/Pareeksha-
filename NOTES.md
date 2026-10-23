# NOTES


- FE-01: Next.js 16 renamed `middleware.ts` to `proxy.ts` (export `proxy`); docs/07 still says middleware.ts. See node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md. (web/proxy.ts)
- FE-01: `openapi-typescript` 7 needs the TypeScript 5 JS API; TypeScript 7 (native) breaks it, so web pins `typescript@5`. (web/package.json)
- FE-01: API spec says base `/api/v1`; if TL-01's OpenAPI paths include that prefix, the generated client paths will too, so `PAREEKSHA_API_URL` (already ending in /api/v1) would double it. Decide when wiring real client. (web/lib/api/client.ts)
