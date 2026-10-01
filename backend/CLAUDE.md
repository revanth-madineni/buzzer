# backend/

## Purpose
The Buzzer server: one Python 3.12 service combining a FastAPI REST API (`/api/*`) and a
python-socketio real-time gateway (`/socket.io/*`), backed by MySQL (durable record) and Redis
(live game state). All application code is in `app/`. This directory adds the container build,
Alembic config, dependencies, and a key-generation script.

## Contents
- `app/` — The application. **Read `app/CLAUDE.md` first.** It maps the six subpackages
  (`models/`, `schemas/`, `common/`, `services/`, `routers/`, `websocket/`, each with its own
  `CLAUDE.md`), the three-layer authorization model, where state lives, and the full data flow
  of one game.
- `Dockerfile` — `python:3.12-slim` + gcc/libmysqlclient (for `asyncmy`), `pip install -r
  requirements.txt`, and copies the source to `/app`. It exposes 8000 but has **no `CMD`**: the
  start command comes from compose (or whatever runs the image in production).
- `alembic.ini` — `script_location = app/migrations`, with `sqlalchemy.url` left blank on
  purpose. `app/migrations/env.py` fills it from `os.environ["DATABASE_URL"]` and imports
  `app.models` for autogenerate.
- `requirements.txt` — FastAPI, uvicorn, gunicorn, python-socketio, SQLAlchemy 2 (async) +
  asyncmy, Alembic, redis, python-jose, passlib + **`bcrypt<4.0`** (pinned; passlib 1.7 breaks on
  bcrypt 4), bleach, rapidfuzz, slowapi, structlog, pydantic(-settings), plus test/load tools
  (pytest, pytest-asyncio, httpx, locust) in the same file.
- `scripts/generate_keys.py` — Generates an RS256 key pair and prints base64 values for
  `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` in `.env`.
- `logs/` — Empty in the repo. The compose file mounts the repo-root `./logs` at `/app/logs`
  instead.

Related, outside this directory: repo-root `scripts/` (`seed_demo.py`, `simulate_players.py`,
`smoke_test_websocket.py`, `setup_venv.sh`) exercise this backend, and
`docker-compose.yml` / `nginx/` wire it up with the frontends.

## How it runs
Dev (`docker compose up`):
- The `backend` service builds from here, bind-mounts `./backend` → `/app` (live reload), and
  runs `uvicorn app.main:asgi_app --reload --host 0.0.0.0 --port 8000`.
- It forces `APP_ENV=development` and waits for healthy `mysql` and `redis`.
- `nginx` on :8080 serves the built frontends at `/host/`, `/player/`, `/admin/` using
  `nginx/nginx.dev.conf` (not reviewed here), which presumably also proxies `/api` and
  `/socket.io` to the backend.

First run:
1. `alembic upgrade head` (inside the container). Until then, app startup blocks in
   `bootstrap_admin`, which retries every 5 s.
2. Set `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env` to get the first admin.
3. Set the JWT keys from `generate_keys.py`. Otherwise tokens die on every restart.

At the request level, the pieces fit together like this (details in `app/CLAUDE.md`):

```
client ──HTTP /api/*──▶ routers/ ──▶ services/ ──▶ models/ (MySQL)
   │                      │  ▲ schemas/ validate    └──▶ Redis (state_service)
   └──WS /socket.io/*──▶ websocket/gateway ──▶ services/ ─┘
                          common/: auth deps, errors, logging, rate limit (used by both)
```

A game round in one line: the host creates a room over REST → everyone connects and
`join_room`s over the socket → the host's `host_advance` cycles QUESTION → RESULTS per question
while players' `submit_answer`s are scored into MySQL and tallied in Redis → `game_over` → exports
and reports are read back from MySQL over REST.

## Gotchas
Backend-wide. `app/CLAUDE.md` and the subpackage files have the rest.
- **Tests live outside this directory**, in repo-root `tests/` (`unit/` and `integration/`).
  The integration suite has its own `pytest.ini`, `conftest.py`, and `requirements.txt`, and
  runs against the live Docker stack. There is no `backend/tests/`. `ruff` (listed in the root
  `CLAUDE.md`) is not in `requirements.txt`.
- **Production config isn't in this repo.** `docker-compose.yml` is dev-only (hard-codes
  `APP_ENV=development`, `--reload`, exposes 3306/8000, uses nginx). Production (Traefik +
  OAuth2 proxy, per comments in `app/`) is configured elsewhere, so check it for:
  - `APP_ENV` set to something other than `development`. It defaults to `"development"`, which
    enables netid-only login, disables rate limits, and exposes `/api/docs`.
  - The server target being `app.main:asgi_app`, not `app.main:app`, or sockets silently
    fail.
  - A **single worker/instance**. `gunicorn` is in the requirements, but the gateway keeps
    timers and sid context in process memory (`app/websocket/CLAUDE.md`).
  - Port 8000 not being reachable except through Traefik. Otherwise the trusted
    `X-Auth-Request-User` header can be spoofed (`app/routers/CLAUDE.md`).
- **Alembic reads `DATABASE_URL` only from the process environment**, not from `.env` via
  `config.py`. Inside the container `env_file` provides it. Running `alembic` on the host needs
  it exported, or it fails with an empty URL.
- The app's `DATABASE_URL` default (`mysql+asyncmy://app_user:password@mysql:3306/buzzer`) only
  resolves inside the compose network.
- `bcrypt` is pinned below 4.0 on purpose. Don't "upgrade" it without replacing or upgrading
  passlib.
- Dev dependencies (pytest, locust, httpx) are installed into the production image because
  there's a single requirements file.
