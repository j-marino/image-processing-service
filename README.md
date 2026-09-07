# Image Processing Service

Built for the
[roadmap.sh Image Processing Service project](https://roadmap.sh/projects/image-processing-service).

## Tech Stack

- **FastAPI**: API layer, JWT auth
- **PostgreSQL**: primary datastore (via SQLModel / async SQLAlchemy)
- **Redis**: caching layer for image retrieval
- **RabbitMQ**: task queue for background image transformations
- **Cloudflare R2** (S3-compatible) image storage, accessed via `aioboto3`
- **Docker Compose**: local orchestration
- **uv**: dependency management

> **Note:** this project is currently set up for local development only.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A Cloudflare R2 bucket (or any S3-compatible bucket) with an API token

## Setup

### 1. Clone the repo and install dependencies

```bash
git clone https://github.com/j-marino/image-processing-service.git
cd image-processing-service
uv sync
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
# Auth
SECRET_KEY='XXXX'
ALGORITHM='HS256'
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Postgres
POSTGRES_DB='X'
POSTGRES_USER='X'
POSTGRES_PASSWORD='X'
DB_URL='postgresql+asyncpg://USER:PASS@localhost:5432/DB'

# Cloudflare R2 (S3-compatible)
CF_API_TOKEN=X
ENDPOINT_URL=X
AWS_ACCESS_KEY_ID=X
AWS_SECRET_ACCESS_KEY=X
BUCKET_NAME=X

# RabbitMQ
RABBITMQ_USER=X
RABBITMQ_PASS=X
RABBITMQ_HOST=X
RABBITMQ_PORT=X
```

- `DB_URL` credentials should match `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` above.
- `ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `BUCKET_NAME` come from your
  Cloudflare R2 dashboard (R2 exposes an S3-compatible API, so standard AWS SDK credentials work).

### 3. Start the supporting services

```bash
docker compose up -d
```

This brings up Postgres, Redis, and RabbitMQ.

### 4. Create the db tables
```bash
python -m app.services.create_tables 
```

### 5. Run the API

```bash
uv run fastapi dev
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 6. Run the background worker

Image transformations are processed asynchronously via RabbitMQ. **The worker must be running
separately** for transform jobs to complete. Without it, jobs will stay `pending` forever.

```bash
uv run python -m app.services.rabbitmq.worker
```

## Running tests

```bash
uv run pytest
```

## Project structure

```
app/
├── main.py # FastAPI app entrypoint
├── config.py # settings
├── dependencies.py # shared FastAPI dependencies
├── models/ # SQLModel table models
├── routers/ # API route handlers
├── schemas/ # request/response schemas
└── services/
    ├── auth/ # JWT auth
    ├── rabbitmq/ # task queue + worker
    └── redis/ # caching
```