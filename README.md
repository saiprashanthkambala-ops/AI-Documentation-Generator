# AI Documentation Generation and Maintenance Assistant

A FastAPI application that safely ingests a project ZIP, builds a deterministic manifest and Python evidence, and uses Gemini to produce evidence-based Markdown documentation. Uploaded source code is never executed.

## Features
- Secure ZIP validation: size, file count, expansion, traversal, depth, and ignored build directories.
- SHA-256 file manifest and Python AST evidence without executing source.
- Server-side Gemini integration with bounded retries and controlled provider errors.
- SQLite persistence for projects and documentation history.
- Markdown viewer, Markdown/PDF/JPG downloads, project history, and health/provider status endpoints.
- PDF export creates a multi-page document; JPG export creates one high-resolution long image from the same generated Markdown.
- Persistent documentation chat lets users propose precise edits, review them, apply them as new revisions, and navigate history with Undo/Redo.
- The API chatbot loads the canonical `documentation-default-format` skill from `backend/skills/` and applies its scope, preservation, structure, styling, and validation rules to chat proposals.

## Setup
Python 3.10+ is recommended.

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## Gemini configuration

This project uses the **Gemini API** for AI document generation. **Ollama is not required**.

Keep the real API key outside the Git repository. Create:

`secrets/gemini.env`

using:

`secrets/gemini.env.example`

Example:

```env
GEMINI_API_KEY=your_real_key_here
GEMINI_MODEL=gemini-3.8-flash
GEMINI_API_TIMEOUT=120
GEMINI_MAX_OUTPUT_TOKENS=8192
```

The `secrets/gemini.env` file is ignored by Git. Never put the real key into frontend JavaScript, HTML, or committed source files.

Gemini 3.8 Flash is a current stable Gemini API model and is configured as the default provider model.

## Run the application

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000.

Gemini generation requires a valid API key and internet access. The rest of the application can start without the key.

## Provider status

Check:

`GET /api/gemini/status`

A configured installation reports the provider, model, and `Ready` status without exposing the API key.

## API
`POST /api/upload`, `POST /api/projects/{id}/generate?doc_type=README`, `GET /api/projects`, `GET /api/projects/{id}`, `GET /api/projects/{id}/download`, `GET /api/projects/{id}/download/pdf`, `GET /api/projects/{id}/download/jpg`, `GET /api/projects/{id}/workspace`, `POST /api/projects/{id}/chat`, `POST /api/projects/{id}/chat/apply`, `POST /api/projects/{id}/chat/undo`, `POST /api/projects/{id}/chat/redo`, `POST /api/projects/{id}/chat/restore/{revision_id}`, `GET /api/projects/{id}/versions`, `GET /api/projects/{id}/documentation-versions`, `GET /api/projects/{id}/changes`, `GET /api/projects/{id}/change-reports`, `POST /api/projects/{id}/maintenance`, `GET /api/projects/{id}/documentation-diff/{version_id}`, `POST /api/projects/{id}/documentation/{version_id}/decision`, `GET /api/gemini/status`, and `GET /api/health`.

## Testing

Run:

```bash
pytest -q
```

Tests mock the Gemini provider, so no real API key is included in automated test execution.

## Security and limitations

The Gemini API key remains server-side and is not committed to the repository. The browser never receives the provider credential. Uploaded source is statically analyzed and never executed. Gemini requests are made by the FastAPI backend and therefore require network access.

## Project structure

`backend/config.py` configuration; `backend/services/zip_handler.py` safe ingestion; `backend/services/intelligence.py` manifest/evidence; `backend/services/gemini_service.py` Gemini provider boundary; `backend/database/` persistence; `frontend/` UI; `secrets/gemini.env.example` safe local configuration template.
