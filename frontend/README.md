# LawFlow — Frontend

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4. Talks to
the FastAPI backend at `NEXT_PUBLIC_API_BASE_URL` (defaults to
`http://localhost:8000` in `.env.local`).

For an overview of the platform — architecture, retrieval pipeline,
benchmarks, screenshots — see the [root README](../README.md).

## Development

```bash
npm install
npm run dev          # http://localhost:3000
```

The backend must be running on port 8000 for auth, chat, and admin
endpoints to work; see [`../backend/README`](../backend/) for setup.

## Regenerating the typed API client

The admin console talks to the backend through a generated TypeScript
client (`app/lib/admin/api.generated.ts`). After changing a backend
endpoint:

```bash
npm run gen:types:full      # dumps OpenAPI + regenerates the client
```

`npm run gen:types` alone skips the dump and reuses the existing
`backend/openapi.json`.

## Layout

```
app/
├── admin/             documents · evaluation · system · settings · jobs
├── components/        ChatMessage · ExplainabilityPanel · admin/* · auth/*
├── lib/               auth + admin API clients, theme provider
├── login/  signup/    auth flows
├── settings/          per-user preferences
├── page.tsx           chat surface
└── layout.tsx         root shell + fonts + theme + auth context
```

## License

[MIT](../LICENSE) — © Dheeraj Reddy Thumma ([@dheerajreddy111](https://github.com/dheerajreddy111)).
