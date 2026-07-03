# Quizz-Back – AGENTS.md

## Stack Technique

- **Framework:** Python 3.11+ + FastAPI
- **ORM:** SQLModel (SQLAlchemy 2.x + Pydantic v2)
- **File Storage:** MinIO (S3-compatible)
- **Auth:** JWT + refresh tokens (httpOnly cookies)
- **Deploy:** Docker + docker-compose
- **Linter:** Ruff (line-length: 100)

## Commands

```bash
# Development
uvicorn app.main:app --reload --port 8080

# Docker
docker-compose up --build

# Seed database
python scripts/seed.py

# Lint (if ruff installed)
ruff check app/
ruff format app/
```

## Dev Launch (Recommended)

Use Docker in dev to mirror prod networking between API and MinIO.

```bash
# 1) Start API + MinIO (+ init bucket/users)
docker compose up --build -d

# 2) Check services
docker compose ps
docker compose logs api --tail=120

# 3) Quick health checks
# API docs (FastAPI default path)
curl http://localhost:8080/openapi.json
# MinIO health
curl http://localhost:9000/minio/health/live

# 4) Stop stack
docker compose down
```

Notes:
- If port `8080` is already used by another container/service, free it first.
- API is exposed on `http://localhost:8080`.
- MinIO API/Console are exposed on `http://localhost:9000` / `http://localhost:9001`.

## Architecture

```
app/
├─ main.py                 # FastAPI app creation + router includes
├─ api/v1/
│  ├─ dependencies.py      # FastAPI dependencies (auth, DB session)
│  └─ routers/             # HTTP layer (endpoints)
│     ├─ authentication.py
│     ├─ users.py
│     ├─ themes.py
│     └─ images.py
├─ core/
│  ├─ config.py            # Settings (env vars)
│  └─ openapi.py           # OpenAPI customization
├─ db/
│  ├─ session.py           # DB engine + session management
│  ├─ models/              # ORM entities
│  └─ repositories/        # Data access layer (CRUD)
├─ features/               # Business logic by domain
│  └─ <feature>/
│     ├─ schemas.py        # Pydantic models (API contracts)
│     └─ services.py       # Use cases / business rules
├─ security/
│  ├─ password.py          # Password hashing (Argon2)
│  └─ tokens.py            # JWT generation/verification
└─ utils/
   ├─ s3.py                # MinIO/S3 client
   └─ images.py            # Image helpers

scripts/
├─ minio-init.sh           # MinIO bootstrap
└─ seed.py                 # Database seeding
```

## Strict Rules

- **No business logic in routers** – Use `features/<feature>/services.py`
- **No direct DB access in routers** – Use repositories
- **All file operations** go through `utils/s3.py`
- **Routers only import:**
  - `features/<feature>/schemas.py`
  - `features/<feature>/services.py`
  - `api/v1/dependencies.py`

## Request Flow

```
HTTP Request
  → Router (app/api/v1/routers/*)
     → Service (app/features/<feature>/services.py)
        → Repository (app/db/repositories/*)
           → Model + Session (app/db/*)

File operations:
  Service → utils/s3.py (MinIO)
```

## Adding New Features

1. Create `app/features/<feature>/`:
   - `schemas.py` – Pydantic models
   - `services.py` – Business logic
2. Create router: `app/api/v1/routers/<feature>.py`
3. Add model: `app/db/models/<feature>.py`
4. Add repository: `app/db/repositories/<feature>.py`
5. Include router in `app/main.py`

## Configuration

- All settings in `app/core/config.py`
- Use `.env` for local config (not committed if sensitive)
- MinIO credentials must be settings, not hardcoded

## API Versioning

All endpoints are under `/api/v1/`

## Code Style

- Ruff formatter (line-length: 100)
- Type hints required
- No comments unless complex logic
- Follow existing patterns in neighboring files
