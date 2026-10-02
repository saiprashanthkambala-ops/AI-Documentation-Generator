# AI Documentation Generation and Maintenance Assistant

A FastAPI application that safely ingests a project ZIP, builds a deterministic manifest and Python evidence, then asks Gemini to produce evidence-based Markdown documentation. Uploads are never executed.

## Features
- Secure ZIP validation: size, file count, expansion, traversal, depth, and ignored build directories.
- SHA-256 file manifest and Python AST evidence without executing source.
- Server-side Gemini integration with bounded retries and controlled provider errors.
- SQLite persistence for projects and documentation history; startup is non-destructive.
- Markdown viewer, download, project history, and health/provider status endpoints.

## Setup
Python 3.10+ is recommended.
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
# put your Gemini key in .env
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
Open http://localhost:8000. Gemini is optional for startup and health checks, but required for generation.

## API
`POST /api/upload`, `POST /api/projects/{id}/generate?doc_type=README`, `GET /api/projects`, `GET /api/projects/{id}`, `GET /api/projects/{id}/download`, `GET /api/projects/{id}/versions`, `GET /api/projects/{id}/documentation-versions`, `GET /api/projects/{id}/changes`, `GET /api/projects/{id}/change-reports`, `POST /api/projects/{id}/maintenance`, `GET /api/projects/{id}/documentation-diff/{version_id}`, `POST /api/projects/{id}/documentation/{version_id}/decision`, `GET /api/gemini/status`, and `GET /api/health`.

## Migrations
After installing dependencies, run `alembic upgrade head`. The baseline migration is additive and preserves existing data. For local development, application startup also creates missing tables non-destructively. `alembic downgrade base` is intentionally conservative: it updates migration bookkeeping but does not drop application tables or historical data.

## Testing
Run `.venv/bin/pytest -q`. Tests cover manifest/hash analysis, impact mapping, ZIP traversal protection, and missing-Gemini-key behavior. A live Gemini test is intentionally not run unless `GEMINI_API_KEY` is configured.

## Security and limitations
The API key remains server-side and is not logged or stored. This is static analysis only: uploaded code is never run. Gemini context is bounded and unsupported languages receive deterministic manifest coverage; deeper maintenance/version comparison is represented in the data model and can be expanded with migrations.

## Project structure
`backend/config.py` configuration; `backend/services/zip_handler.py` safe ingestion; `backend/services/intelligence.py` manifest/evidence; `backend/services/gemini_service.py` provider boundary; `backend/database/` persistence; `frontend/` UI.
