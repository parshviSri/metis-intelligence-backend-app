# Metis Intelligence Backend

Production-ready backend boilerplate for a SaaS business diagnostic platform built with FastAPI, PostgreSQL, SQLAlchemy, Alembic, and OpenAI-ready service boundaries.

## Project Structure

```text
app/
├── main.py
├── core/
│   ├── config.py
│   ├── database.py
│   └── logging.py
├── api/
│   └── v1/
│       └── routes/
│           └── diagnostic.py
├── models/
│   └── diagnostic.py
├── schemas/
│   └── diagnostic_schema.py
├── services/
│   └── llm_service.py
├── repositories/
│   └── diagnostic_repo.py
└── utils/
```

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and update values.
4. Run the application:

   ```bash
   uvicorn app.main:app --reload
   ```

## Alembic

Initialize the first migration when ready:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```
The application is a small FastAPI backend organized as a layered service: HTTP routes at the top, persistence and LLM logic in separate layers underneath, and shared infrastructure in `core/`.

**Top-Level Shape**

The runtime starts in [app/main.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/main.py). That file does four main things:
1. Initializes logging.
2. Builds the FastAPI app and CORS middleware.
3. Creates database tables on startup via SQLAlchemy metadata.
4. Mounts the v1 API router under the configured prefix, so the main business endpoints live under `/api/v1`.

The app configuration is centralized in [app/core/config.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/core/config.py). It reads environment variables like `DATABASE_URL`, `OPENAI_API_KEY`, `LLM_MODEL`, and `CORS_ORIGINS`, and exposes them through a cached `get_settings()` helper.

Database setup is in [app/core/database.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/core/database.py). That file defines:
- `Base` for SQLAlchemy models
- `engine` for PostgreSQL connections
- `SessionLocal` for DB sessions
- `get_db()` as the FastAPI dependency used by routes

Logging is isolated in [app/core/logging.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/core/logging.py), and `main.py` also adds request/response logging middleware plus a `/health` endpoint.

**Application Layers**

The API layer is in [app/api/v1/routes/diagnostic.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/api/v1/routes/diagnostic.py). This is the main feature of the app. It exposes:
- `POST /api/v1/diagnostic/submit`
- `GET /api/v1/diagnostic/{id}`
- `GET /api/v1/diagnostics`

Those route handlers are intentionally thin. They validate input with Pydantic, call the repository layer for DB writes/reads, call the LLM service for report generation, and return typed responses.

The schema layer is in [app/schemas/diagnostic_schema.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/schemas/diagnostic_schema.py). It defines:
- `DiagnosticRequest` for incoming frontend payloads
- `Insight` and `Recommendation` for report content
- `DiagnosticResponse` for the full API response
- `DiagnosticSummary` for list responses

The model layer is in [app/models/diagnostic.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/models/diagnostic.py). There are two tables:
- `Diagnostic`: stores the submitted business input, including full raw JSON plus searchable columns like `business_name` and `business_type`
- `Report`: stores the LLM output, including raw response text plus parsed structured data like `health_score`, `insights_json`, and `recommendations_json`

The repository layer is in [app/repositories/diagnostic_repo.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/repositories/diagnostic_repo.py). It owns database access:
- create a diagnostic
- create a report
- fetch a diagnostic by id
- fetch the latest report for a diagnostic
- list diagnostics

The service layer is in [app/services/llm_service.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/services/llm_service.py). It encapsulates all LLM behavior. `generate_report()` either:
- returns a deterministic mock report if `LLM_MOCK_MODE=true`
- calls OpenAI with a structured JSON prompt
- falls back to the mock report if the OpenAI call fails

Shared helper logic is in [app/utils/__init__.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/utils/__init__.py). That module normalizes incoming payloads, safely coerces numeric fields, and computes a fallback health score when LLM output cannot be parsed cleanly.

**Request Flow**

For the main submit flow in [app/api/v1/routes/diagnostic.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/app/api/v1/routes/diagnostic.py):
1. The client sends a validated `DiagnosticRequest`.
2. The payload is cleaned with `normalise_payload()`.
3. A `Diagnostic` row is written to the database.
4. The LLM service generates a JSON report string.
5. The route parses the LLM response into `health_score`, `insights`, and `recommendations`.
6. A `Report` row is saved.
7. The API returns a `DiagnosticResponse`.

That means the app is structured around one core business workflow: ingest business metrics, generate an AI-backed diagnostic, persist both the raw input and the generated output, and expose retrieval/list endpoints.

**Database and Migrations**

Schema evolution is managed with Alembic in [alembic/env.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/alembic/env.py) and [alembic/versions/0001_initial_schema.py](/Users/parshvisrivastava/Desktop/metis-intelligence-backend-app/alembic/versions/0001_initial_schema.py). The migration creates the `diagnostics` and `reports` tables and the basic indexes.

One practical detail: startup currently runs `Base.metadata.create_all(...)` in `main.py`, which is convenient for development, while Alembic is the intended production migration path.

In short, the application is a conventional FastAPI backend with clear separation between:
- infrastructure: `core/`
- HTTP routes: `api/`
- validation contracts: `schemas/`
- database entities: `models/`
- data access: `repositories/`
- business/LLM logic: `services/`
- pure helpers: `utils/`
