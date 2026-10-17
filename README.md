# MAWAPRESS

Bilingual (Nepali/English) news portal. `backend/` is the FastAPI API (see `backend/README.md`),
`frontend/` is the Next.js app, `docs/api-contract.md` describes the API for client developers.

## Frontend

Next.js 15 with the public site and the newsroom admin in one app. Setup, environment variables, the
`/api` proxy and the typed API client are documented in `frontend/README.md`.

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000, proxies /api to http://127.0.0.1:8000
npm run lint && npm run typecheck && npm test && npm run build
npm run gen:api    # re-export contracts/openapi.json and regenerate src/lib/api/schema.d.ts
```
