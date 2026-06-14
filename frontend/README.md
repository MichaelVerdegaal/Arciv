# Arciv frontend

Astro on-demand (SSR) UI for browsing the archive. It is a pure presentation
tier: it only speaks HTTP to the Arciv backend API and never opens the database
or reads `saved/` directly. Page markdown is rendered to HTML and sanitized
server-side.

## Develop

```bash
npm install
ARCIV_API_URL=http://localhost:8000 npm run dev   # http://localhost:4321
```

`ARCIV_API_URL` points at a running backend (`uv run uvicorn arciv_api.app:app`
from the repo root). It defaults to `http://localhost:8000`.

## Build and run

```bash
npm run build
ARCIV_API_URL=http://backend:8000 PORT=4321 npm start
```

`npm run build` produces a standalone Node server at `dist/server/entry.mjs`
(`npm start` runs it). `npm run check` type-checks the project.

## Pages

- `/` — archive browse: filter by domain/status, sort, page through results.
- `/page/<slug>` — one page: rendered markdown, metadata, source files. A known
  slug that is not yet parsed shows a pending/failed notice; an unknown slug is
  a 404.
- `/domains` — domains with page counts, linking into a filtered browse.
