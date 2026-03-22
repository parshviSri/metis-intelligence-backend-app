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
