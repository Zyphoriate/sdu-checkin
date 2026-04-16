# Attendance Auto Check-In

[English](./README.md) | [简体中文](./README_CN.md)

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](#)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](#)
[![SQLite](https://img.shields.io/badge/SQLite-local%20storage-003B57?logo=sqlite&logoColor=white)](#)

Self-hosted multi-user attendance automation service with a small web console, per-account schedules, manual runs, local logs, and Docker deployment.

## Highlights

- Multi-account management with independent schedules
- Manual run and scheduled run support
- Configurable overwrite strategy for existing daily records
- Local encrypted password storage with Fernet
- Session-based admin authentication
- Login rate limiting for admin access
- Docker-friendly self-hosted deployment

## Stack

- Backend: FastAPI
- Storage: SQLite
- Scheduler: in-process polling loop
- Frontend: vanilla HTML, CSS, and JavaScript
- Packaging: Docker and docker compose

## Quick Start

### 1. Prepare environment

Copy the example file and fill in your own values:

```bash
cp .env.example .env
```

Generate the admin password hash:

```bash
python3 -c "from app.auth import hash_admin_password; print(hash_admin_password('replace-with-your-admin-password'))"
```

Put the output into `.env` as `CHECKIN_ADMIN_PASSWORD_HASH`.

### 2. Run with Docker

Create a `docker-compose.yml`:

```yaml
services:
  auto-checkin:
    image: ghcr.io/zyphoriate/sdu-checkin:main
    container_name: auto-checkin
    restart: unless-stopped
    ports:
      - "${CHECKIN_BIND_IP:-127.0.0.1}:18081:8080"
    environment:
      CHECKIN_ADMIN_PASSWORD_HASH: "${CHECKIN_ADMIN_PASSWORD_HASH:?set CHECKIN_ADMIN_PASSWORD_HASH}"
      CHECKIN_AUTH_COOKIE_SECURE: "${CHECKIN_AUTH_COOKIE_SECURE:-false}"
      CHECKIN_BASE_URL: "${CHECKIN_BASE_URL:?set CHECKIN_BASE_URL}"
      CHECKIN_DATA_DIR: /data
      CHECKIN_LOGIN_LIMIT_BLOCK_SECONDS: 900
      CHECKIN_LOGIN_LIMIT_MAX_ATTEMPTS: 5
      CHECKIN_LOGIN_LIMIT_WINDOW_SECONDS: 300
      CHECKIN_SERVICE_TIMEZONE: Asia/Shanghai
      CHECKIN_SCHEDULER_INTERVAL_SECONDS: 60
      CHECKIN_SCHEDULER_RETRY_LIMIT: 3
      CHECKIN_REQUEST_TIMEOUT_SECONDS: 20
    volumes:
      - ./data:/data
```

Then start the service:

```bash
docker compose --env-file .env up -d
```

Open `http://127.0.0.1:18081/`.

### 3. Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a
source .env
set +a
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open `http://127.0.0.1:8080/`.

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `CHECKIN_BASE_URL` | Yes | Base URL of the upstream attendance system |
| `CHECKIN_ADMIN_PASSWORD_HASH` | Yes | Admin password hash generated with `app.auth.hash_admin_password()` |
| `CHECKIN_DATA_DIR` | No | Local data directory for SQLite and Fernet key |
| `CHECKIN_BIND_IP` | No | Host bind address for Docker publishing; default `127.0.0.1` |
| `CHECKIN_AUTH_COOKIE_SECURE` | No | Set to `true` when the service is behind HTTPS |
| `CHECKIN_AUTH_SESSION_TTL_SECONDS` | No | Admin session lifetime |
| `CHECKIN_LOGIN_LIMIT_MAX_ATTEMPTS` | No | Max failed admin login attempts per source IP in the window |
| `CHECKIN_LOGIN_LIMIT_WINDOW_SECONDS` | No | Failure counting window for login rate limiting |
| `CHECKIN_LOGIN_LIMIT_BLOCK_SECONDS` | No | Temporary block duration after too many failed logins |
| `CHECKIN_SERVICE_TIMEZONE` | No | Scheduler timezone |
| `CHECKIN_SCHEDULER_INTERVAL_SECONDS` | No | Scheduler polling interval |
| `CHECKIN_SCHEDULER_RETRY_LIMIT` | No | Retry limit for scheduled runs per day |
| `CHECKIN_REQUEST_TIMEOUT_SECONDS` | No | Timeout for upstream requests |
| `CHECKIN_ENCRYPTION_KEY` | No | Optional static Fernet key; otherwise generated on first start |

See [.env.example](./.env.example) for a safe template.

## Security Notes

- This project is meant for self-hosting, not direct public exposure.
- Default Docker publishing binds to `127.0.0.1` only.
- If you expose it to other machines, put it behind HTTPS and set `CHECKIN_AUTH_COOKIE_SECURE=true`.
- Use this only against systems you are authorized to automate.

## Project Structure

```text
app/
  auth.py         admin auth, session signing, login throttling
  client.py       upstream HTTP client
  config.py       environment-based settings
  crypto.py       Fernet encryption wrapper
  db.py           SQLite repository layer
  main.py         FastAPI app and routes
  scheduler.py    in-process scheduler loop
  service.py      check-in orchestration logic
  static/         web console assets
tests/
  test_main_auth.py
  test_models.py
  test_service.py
data/
  .gitkeep
```

## Verification

```bash
python3 -m compileall app tests
python3 -m unittest discover -s tests
```

## Operational Notes

- Moving the service to another machine requires migrating both the database and Fernet key if you want existing encrypted credentials to remain usable.
- The scheduler is in-process; do not run multiple active instances against the same database unless you add leader election or locking.
