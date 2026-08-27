# Decrunch

Overload-proof semester calendar frontend. React + Vite + Lucide icons, driven by realistic mock data so Backend, Gemini AI, and Computer Vision teammates can wire APIs later.

## Quick start

```bash
npm install
npm run dev
```

Then open the URL Vite prints (usually `http://localhost:5173`).

## Run the backend + AI pipeline

The frontend proxies `/api` requests to the Flask service at port 5000. In a
second terminal, set up the Python environment and start it:

```bash
uv sync --group dev
uv run python backend/app.py
```

Create `.env` from `.env.example` and add your `GEMINI_API_KEY` to enable
Gemini extraction. `DATABASE_URL` is ready for the database/seed workflow;
the current task repository is in memory, so uploads remain available only
while the backend is running.

## User flow

1. **Welcome** — drag/drop or browse a PDF / JPEG / PNG syllabus  
2. **Processing modal** — animated CV → Gemini → Backend pipeline  
3. **Calendar** — weekly grid or timeline list, filter by course  
4. **Sidebar** — Week 4 high-risk overload + Gemini early-start checklists  

## Project structure

```
src/
  App.jsx                 # State machine (welcome → processing → calendar)
  mockData.js             # Courses, 20 assignments, overload + AI recs
  index.css               # Design system
  components/
    Header.jsx
    WelcomeHero.jsx
    UploadModal.jsx
    CalendarView.jsx
    OverloadSidebar.jsx
```

## API integration points

Comments in `App.jsx`, `UploadModal.jsx`, `CalendarView.jsx`, and `OverloadSidebar.jsx` mark where to plug in:

| Team | Suggested endpoint |
|------|--------------------|
| Computer Vision / Backend | `POST /api/syllabus/upload` |
| Job status | `GET /api/jobs/:id/status` |
| Calendar merge | `GET /api/calendar` |
| Overload engine | `GET /api/overload-risks` |
| Gemini smoothing | `GET /api/ai/recommendations` |

Replace imports from `mockData.js` with `fetch` / React Query once those routes exist.

## Scripts

- `npm run dev` — local development  
- `npm run build` — production build to `dist/`  
- `npm run preview` — serve the production build  
