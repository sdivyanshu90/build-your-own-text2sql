# Docker Deployment

## Local stack (one command)

```bash
docker compose up --build
```

This starts three services defined in [`docker-compose.yml`](../../docker-compose.yml):

```mermaid
flowchart LR
    DB[(postgres:16)] -->|healthy| MIG[migrate: alembic upgrade + seed]
    MIG -->|completed| API[api: uvicorn]
    API -->|:8000| USER[you]
```

- **db** — PostgreSQL 16 with a healthcheck.
- **migrate** — one-shot job that runs `alembic upgrade head` then `scripts/seed.py`,
  then exits.
- **api** — the service, started only after `migrate` completes successfully.

The API comes up on <http://localhost:8000> (docs at `/api/v1/docs`). The default
LLM provider is the deterministic fake, so **no credentials are required**.

```bash
docker compose down -v          # stop and remove the volume
```

## The image

[`Dockerfile`](../../Dockerfile) is a **multi-stage** build:

1. **builder** — installs the package (with the `postgres` driver) into an isolated
   virtualenv.
2. **runtime** — a slim, **non-root** image (`app` user) that copies only the venv
   and runtime assets (migrations, alembic config, scripts, source). It declares a
   `HEALTHCHECK` that hits `/api/v1/health/live` using stdlib `urllib` (no `curl`
   needed).

Build and run standalone:

```bash
docker build -t text-to-sql-engine .
docker run --rm -p 8000:8000 \
  -e T2SQL_LLM_PROVIDER=fake \
  -e T2SQL_DATABASE_URL=sqlite:////app/data/app.db \
  text-to-sql-engine \
  sh -c "python scripts/init_db.py --drop --seed && uvicorn text_to_sql.main:app --host 0.0.0.0 --port 8000"
```

## Notes

- The container binds `0.0.0.0` intentionally (it's behind the platform's network).
- Provide secrets (e.g. `OPENAI_API_KEY`) via your orchestrator's secret mechanism,
  not baked into the image.
- For production, point `T2SQL_READONLY_DATABASE_URL` at a read-only role and run
  the API behind a TLS-terminating reverse proxy (see
  [production](production.md)).
