# Command Center

Creator OS Command Center runs on port 4100.

## Local Development

```bash
ALLOW_INSECURE_LOCAL=1 npm run dev
```

Use this mode for local browser work at `http://localhost:4100`.

## Token Mode

```bash
CREATOR_OS_API_TOKEN=<token> npm run dev
```

Token mode keeps API routes protected. API clients must send
`Authorization: Bearer <token>`.
