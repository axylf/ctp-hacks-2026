# Decrunch

Decrunch reads course syllabi, extracts deliverables from grading sections and
tentative plans, and organizes them by the week printed in the syllabus.

## Stack and tools

| Area | Libraries and tools |
|------|---------------------|
| Frontend | React 19, Vite 8, Lucide React, CSS |
| Backend | Python 3.10+, Flask, Flask-CORS |
| AI and extraction | Google Gemini (`google-genai`), Pydantic, pypdf, PyMuPDF, OpenCV, Pillow, Tesseract / pytesseract |
| Processing | RapidFuzz, python-dateutil, NumPy |
| Database | PostgreSQL, psycopg 3, `psql` migrations |
| Development | Cursor, uv, npm, pytest, Oxlint |

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Then open the URL Vite prints (usually `http://localhost:5173`).

## Run the backend + AI pipeline

The frontend proxies `/api` requests to the Flask service at the
`VITE_BACKEND_URL` in `.env` (port 5001 in the local setup). In a second
terminal, set up the Python environment and start it:

```bash
uv sync --group dev --group db
uv run --group db python backend/app.py
```

Create `.env` from `.env.example` and add your `GEMINI_API_KEY` to enable
Gemini extraction. The backend reads `PORT`; Vite reads `VITE_BACKEND_URL`
from the same file. The provided local configuration uses port 5001.

## Database setup

Apply the schema once after setting `DATABASE_URL` in `.env`:

```bash
set -a
source .env
set +a
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
```

The repository currently uses in-memory task storage during a backend run.
The PostgreSQL schema and seed script are ready for persistent storage:

```bash
uv run --group db python ml/scripts/seed_db.py
```

## User flow

1. **Upload or scan** — add a PDF or photographed syllabus pages.
2. **Extract** — Gemini reads the document; the offline parser handles PDF text and tentative-plan tables as a fallback.
3. **Review** — calendar groups Labs, Exams, and other deliverables by printed week number/range.
4. **Plan** — workload analysis and AI recommendations identify conflicts.

## Project structure

```
frontend/src/
  App.jsx                 # Upload and API state
  api.js                  # Flask API client
  index.css               # Design system
  components/
    Header.jsx
    WelcomeHero.jsx
    UploadModal.jsx
    CalendarView.jsx
    OverloadSidebar.jsx
```

## API routes

| Route | Purpose |
|------|---------|
| `POST /api/syllabus/upload` | Extract a PDF syllabus |
| `POST /api/syllabus/scan` | Extract one or more camera images |
| `POST /api/analyze` | Analyze cross-course workload and recommendations |
| `GET /api/tasks` | List tasks in the current backend session |
| `PATCH /api/tasks/:id` | Update a task |

## Scripts

- `cd frontend && npm run dev` — local development
- `cd frontend && npm run build` — production build to `frontend/dist/`
- `cd frontend && npm run preview` — serve the production build
