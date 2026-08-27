# Syllabus Intelligence Engine — ML/AI Plan

**Owner:** ML/AI track
**Scope:** everything from *"a student hands us a syllabus"* to *"here is structured, prioritized, conflict-analyzed JSON."*
**Out of scope (teammates own it):** persistent database, auth, production frontend, push-notification delivery.
We build a thin **Flask Blueprint** + a bare demo page — **enough to run and test end-to-end today, and to be linked into the real backend later** by swapping the storage layer.

> **Status: built and verified.** 123 tests pass with no API key and no network.
> Both buttons were exercised over real HTTP against a running server; see §11.

---

## 0. TL;DR

```
PDF file ──┐
           ├─→ ingest ─→ route ─→ Gemini structured extraction ─→ normalize ─→ analyze ─→ JSON
camera  ───┘   (text/img)  (native vs vision)                     (dates,       (overlap,
                                                                   dedupe,       priority,
                                                                   inference)    advice)
```

Two upload buttons, one pipeline, one JSON contract. Deterministic post-processing wraps a
non-deterministic model so the output is testable.

---

## 1. What the sample syllabus taught us (this drives the whole design)

I probed the uploaded fixture — `CMP 405/743: Intro to Networks`, Lehman College, Spring 2026:

| Property | Value |
|---|---|
| Pages | 3 |
| Extractable text layer | **yes** — 5,954 chars (2113 / 1675 / 2164) |
| Date-like strings (`Mar 10`, `3/10`, …) | **ZERO** |
| Gradeable items stated | ~4 programming assignments (40%), participation (10%), midterm (20%), final (30%) |
| Explicit due dates | none |

This is not an edge case — it is the *common* case. A large fraction of real syllabi name the
deliverables and their grade weights but publish dates on the LMS instead.

**Four design consequences, all load-bearing:**

1. **Extraction must not require dates.** A task with `due_date: null` is a first-class result,
   not a failure. The naive "find the dates, done" approach scores 0% on this fixture.
2. **Every task carries `confidence` + `needs_review`.** The UI surfaces low-confidence rows for
   the student to fix — which is exactly the "edit incorrect information" feature the product spec
   already asks for. Uncertainty becomes a feature instead of a bug.
3. **Date inference is a separate, explainable stage.** Given a term start/end (asked once at
   upload, or defaulted per school calendar), we place undated work on a schedule:
   assignments spread evenly, midterm ≈ week 8, final in exam week. Each inferred date is tagged
   `date_source: "inferred"` so it renders differently (dashed outline) and never masquerades as fact.
4. **Grade weight is the best priority signal we get.** `40% / 10% / 20% / 30%` is extractable
   even when dates aren't, and a 30%-of-grade final outranks a 5% quiz regardless of proximity.

The fixture also has a hostile detail worth testing: `CMP 405/743` is **two cross-listed course
numbers in one document**, with different prerequisites. The extractor must emit one course, not two.

---

## 2. Architecture

### 2.1 Pipeline stages

| # | Stage | Job | Deterministic? |
|---|---|---|---|
| 1 | **Ingest** | PDF → text + page images; camera frames → images | yes |
| 2 | **Route** | pick native-text vs vision path by text density | yes |
| 3 | **CV preprocess** | deskew, perspective-correct, denoise, binarize photos | yes |
| 4 | **Extract** | Gemini call with an enforced response schema | **no** |
| 5 | **Normalize** | resolve dates, dedupe, infer missing schedule, score priority | yes |
| 6 | **Analyze** | weekly load buckets, overlap detection | yes |
| 7 | **Advise** | recommendations + task breakdown (rules first, Gemini for prose) | mixed |

Only stage 4 (and half of 7) is model-driven. Everything else is pure functions over data — which
is why the test suite can be meaningful rather than a smoke test.

### 2.2 Path routing (stage 2)

```
text_chars_per_page = len(text) / n_pages

>= 300  → NATIVE TEXT   send text to Gemini (cheap, fast, exact)
<  300  → VISION        render/preprocess images, send to Gemini multimodal
mixed   → HYBRID        per-page decision, results merged
```
Our fixture is 1,984 chars/page → native text. A phone photo is 0 → vision. Scanned-image PDFs
(text layer absent) fall into vision automatically, which is the whole point of the heuristic.

### 2.3 Computer-vision preprocessing (stage 3, camera path)

Applied to every camera frame before it reaches the model, in OpenCV:

1. **Document detection** — grayscale → Gaussian blur → Canny → largest 4-point contour.
2. **Perspective transform** — warp that quad to a flat rectangle (kills the angled-photo problem).
3. **Deskew** — minimum-area rectangle on the text mask, rotate to horizontal.
4. **Denoise + adaptive threshold** — `cv2.adaptiveThreshold` for even lighting on shadowed pages.
5. **Upscale short edge to ≥ 1600px** — small text is the #1 cause of vision-model misreads.
6. **Quality gate** — Laplacian variance blur score; below threshold we return
   `{"error": "too_blurry", "retake": true}` *before* burning a Gemini call.

Multi-page capture is supported: the client posts N frames, each is preprocessed, and all go into
one extraction call so cross-page context (course name on page 1, dates on page 3) survives.

### 2.4 Gemini extraction (stage 4)

- **SDK:** `google-genai` (the current unified Google Gen AI SDK).
- **Model:** `gemini-2.5-flash` by default, `GEMINI_MODEL` env var to swap. Flash is the right
  call — this is bounded structured extraction, not reasoning, and it keeps a demo responsive.
- **Structured output:** pass our Pydantic schema as `response_schema` with
  `response_mime_type="application/json"`. The model *cannot* return malformed shapes, which
  removes an entire class of parse-failure bugs.
- **`temperature=0`** for reproducibility.
- **Prompt strategy:** a system prompt that (a) enumerates the task taxonomy, (b) states
  explicitly *"if no due date is given, return null — do not guess"*, (c) demands grade weights,
  (d) requires a per-field confidence, (e) one few-shot example built from a dateless syllabus so
  the null-date behavior is demonstrated, not just described.
- **Resilience:** exponential-backoff retry on 429/5xx; on total failure the pipeline degrades to
  the offline regex extractor (§2.5) rather than returning nothing.

### 2.5 Offline fallback extractor

A regex + heuristic extractor that needs no API key: finds `Assignment N`, `Midterm`, `Final`,
`Quiz N`, percentage weights, and common date formats via `dateparser`. It serves three purposes:
it is the CI extractor (no key, no cost, no flake), the degraded-mode path when Gemini is down,
and the **baseline** the eval harness measures Gemini against. If Gemini can't beat regex on our
labeled set, we'd want to know that.

### 2.6 Normalization (stage 5)

- **Date resolution** — `"Week 5"`, `"Mon 3/10"`, `"the Friday before spring break"` → ISO date,
  anchored on the term calendar. Year disambiguation from term bounds (a `3/10` in a Spring 2026
  course is 2026-03-10, never 2025).
- **Schedule inference** — undated items placed as described in §1.3, all tagged `inferred`.
- **Dedupe** — fuzzy title match (`rapidfuzz`) within a course; "HW 3" and "Homework 3" merge.
- **Priority scoring** — deterministic and explainable, no model involved:

```python
score = 0.35*type_weight + 0.30*grade_pct_norm + 0.20*proximity + 0.15*week_load
# type_weight: final/midterm 1.0 · project/paper 0.85 · presentation 0.7
#              assignment 0.55 · quiz 0.35 · reading 0.15
# → CRITICAL ≥0.75 · HIGH ≥0.55 · MEDIUM ≥0.35 · LOW otherwise
```
Every task ships a `priority_reason` string so the UI can explain itself and so a wrong priority
is debuggable instead of mysterious.

### 2.7 Overlap detection (stage 6)

Two views, because they answer different questions:

- **ISO-week buckets** → what the calendar highlights (weeks are how students think).
- **Rolling 7-day window, stepped daily** → what actually detects crunch. A paper on Friday and
  two exams the following Monday is a brutal 4-day stretch that ISO weeks split in half and miss.

```python
effort_units = {exam:5, final:5, midterm:5, project:5, paper:4,
                presentation:3, assignment:3, quiz:2, reading:1}
load = sum(effort_units[t.type] * (1 + t.grade_pct/100) for t in window)
```
Severity: `load ≥ 12` or `≥3 major` → **critical**; `load ≥ 8` or `≥2 major` → **heavy**;
`load ≥ 5` → **moderate**. Thresholds live in one config dict so they're tunable from the eval
harness rather than scattered through the code.

### 2.8 Recommendations (stage 7)

Rules pick *what* to say, Gemini writes *how* to say it — so the advice is never hallucinated,
only phrased.

| Trigger | Recommendation |
|---|---|
| ≥3 major deliverables in one window | start the largest N days early; auto-generate subtasks |
| Project/paper ≥ 20% of grade | split into outline → draft → revise → submit, back-dated from the due date |
| Two exams < 48h apart | front-load study for the second one |
| Task overdue and incomplete | escalate priority, surface at top of list |

Subtask generation is Gemini's job (it knows a research paper decomposes differently than a
socket-programming assignment), constrained to a schema of 3–6 subtasks each with a `days_before`
offset. `days_before` is validated to be positive and within the parent's lead time before any
subtask date is computed.

---

## 3. Repo layout

```
ml/
├── app/
│   ├── __init__.py             create_app() factory, CORS, error handlers
│   ├── routes.py               Flask Blueprint — register on the real backend
│   ├── storage.py              Repository protocol + in-memory implementation
│   ├── config.py               settings, thresholds, model name
│   ├── schemas.py              Pydantic v2 — THE integration contract
│   ├── pipeline.py             orchestrates stages 1-7
│   ├── ingest/
│   │   ├── pdf.py              pypdf text + PyMuPDF page rasterization
│   │   ├── image.py            OpenCV preprocessing (§2.3)
│   │   └── router.py           native vs vision decision
│   ├── extract/
│   │   ├── gemini.py           google-genai client, structured output, retries
│   │   ├── prompts.py          system prompt + few-shot
│   │   └── fallback.py         offline regex extractor
│   ├── normalize/
│   │   ├── dates.py  dedupe.py  priority.py  infer.py
│   └── analyze/
│       ├── overlap.py          weekly + rolling-window load
│       └── recommend.py        rules + Gemini phrasing
│   └── static/demo.html        two buttons: Upload PDF · Scan with Camera
├── tests/                      see §6
├── eval/
│   ├── labels/                 hand-labeled ground truth per fixture
│   └── run_eval.py             precision/recall/F1 report
└── pyproject.toml
```

**Python 3.12 via `uv`.** The machine's system Python is 3.9.6, which several of these libraries
have dropped; `uv venv --python 3.12` sidesteps that without touching the system install.

---

## 4. The data contract (this is the seam teammates build against)

Frozen early so frontend and backend can develop in parallel against a fixture file.

```jsonc
{
  "course": {
    "code": "CMP 405/743",          // cross-listed → ONE course
    "name": "Intro to Networks",
    "institution": "Lehman College, CUNY",
    "term": "Spring 2026",
    "instructor": "Matthew P. Johnson",
    "meeting_times": null,
    "confidence": 0.95
  },
  "tasks": [{
    "id": "cmp405-final",
    "course_code": "CMP 405/743",
    "title": "Final Exam",
    "type": "final",              // assignment|quiz|exam|midterm|final|project|paper|presentation|reading|other
    "due_date": "2026-05-20",
    "due_time": null,
    "date_source": "inferred",    // explicit | inferred | unknown
    "grade_pct": 30.0,
    "priority": "critical",
    "priority_score": 0.82,
    "priority_reason": "30% of final grade; exam-type; term-end crunch window",
    "estimated_hours": 10,
    "completed": false,
    "needs_review": true,         // → UI nudges the student to confirm
    "confidence": 0.55,
    "source_page": 2,
    "source_quote": "30% - final",   // provenance: student can verify against the PDF
    "subtasks": []
  }],
  "workload_analysis": {
    "windows": [{
      "start": "2026-05-11", "end": "2026-05-17",
      "load_score": 13.5, "severity": "critical",
      "task_ids": ["cmp405-final", "..."],
      "label": "3 major deadlines in 7 days"
    }]
  },
  "recommendations": [{
    "type": "start_early",
    "target_task_id": "cmp405-pa4",
    "message": "PA4 lands the same week as your final. Start it 6 days early.",
    "suggested_subtasks": [{"title": "Design + socket skeleton", "days_before": 6}]
  }],
  "meta": {
    "pipeline_path": "native_text",   // native_text | vision | hybrid | fallback
    "model": "gemini-2.5-flash",
    "warnings": ["no explicit due dates found; dates inferred from term calendar"],
    "processing_ms": 3140
  }
}
```

`source_quote` matters more than it looks: it lets the student see *why* the AI thinks something,
which is the difference between a tool they trust and one they abandon after the first wrong date.

---

## 5. API surface (thin, replaceable)

| Method | Route | Body | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | — | liveness + whether a Gemini key is configured |
| `POST` | `/api/syllabus/upload` | multipart `file` (PDF), optional `term_start`/`term_end` | **file-upload button** |
| `POST` | `/api/syllabus/scan` | multipart `images[]` (1..N JPEG/PNG) | **camera button** |
| `POST` | `/api/analyze` | `{tasks: [...]}` from many courses | cross-course overlap + advice |
| `GET` | `/api/tasks` | — | list stored tasks |
| `PATCH` | `/api/tasks/<id>` | `{completed, due_date, title, ...}` | mark done / correct a wrong extraction |
| `GET` | `/api/demo/sample` | — | returns the golden fixture JSON, no key needed |

Two distinct endpoints for the two buttons — not one overloaded route — because the camera path
has genuinely different preprocessing, different failure modes (`too_blurry`, `no_document_found`),
and different retry UX.

Storage is a `Repository` protocol with an in-memory implementation. The backend is **Flask**, so
this ships as a Blueprint they register on their own app — no second process and no cross-service
HTTP hop:

```python
from ml.app.routes import syllabus_bp
app.register_blueprint(syllabus_bp)
app.extensions["syllabus_repo"] = PostgresRepository(...)   # six methods, see app/storage.py
```

That is the "link it later" plan, made concrete.

`/api/analyze` is the multi-course entry point: single-syllabus responses already include analysis
for that course, but true cross-course overlap detection — the flagship feature — needs the union
of tasks, which only the backend holds.

### Demo page (`static/demo.html`)

Deliberately ugly, deliberately functional — it exists to prove the ML path works and to be
thrown away when the real UI arrives:

- **Button 1 — Upload Syllabus PDF:** `<input type="file" accept="application/pdf">` → `/upload`.
- **Button 2 — Scan with Camera:** `getUserMedia` live preview + capture on desktop;
  falls back to `<input type="file" accept="image/*" capture="environment">` on mobile, which
  opens the native camera directly. Multi-shot supported for multi-page syllabi.
- Renders returned tasks in a table, colors crunch windows red, prints raw JSON for debugging.

---

## 6. Test plan

`pytest`, and **no test ever calls the real Gemini API** — the client is mocked at the boundary so
the suite is free, offline, deterministic, and CI-safe.

### 6.1 Unit

| Test | Asserts |
|---|---|
| `test_pdf_ingest` | fixture yields 3 pages, ~5954 chars, non-empty per page |
| `test_router_native` | 1984 chars/page → `native_text` |
| `test_router_vision` | image-only input → `vision` |
| `test_cv_deskew` | synthetic 12°-rotated page → residual skew < 1° |
| `test_cv_perspective` | synthetic trapezoid → warped to rectangle, aspect within tolerance |
| `test_cv_blur_gate` | blurred image rejected pre-API; sharp image passes |
| `test_dates_relative` | `"Week 5 Monday"` + term start 2026-01-26 → `2026-02-23` |
| `test_dates_year_inference` | `"3/10"` in Spring 2026 → `2026-03-10`, never 2025 |
| `test_dedupe` | `"HW 3"` + `"Homework 3"` → one task |
| `test_priority_ordering` | 30% final > 5% quiz even when the quiz is sooner |
| `test_priority_reason` | every task gets a non-empty explanation |
| `test_infer_schedule` | 4 undated assignments → 4 spread dates, all `date_source="inferred"` |

### 6.2 Extraction contract

| Test | Asserts |
|---|---|
| `test_schema_enforced` | mocked Gemini JSON validates cleanly into Pydantic models |
| `test_malformed_response` | garbage from the model → fallback path, no crash |
| `test_api_error_retry` | 429 then success → one retry, correct result |
| `test_api_down_degrades` | persistent failure → offline extractor result, `path="fallback"` |
| `test_no_hallucinated_dates` | mocked null-date response → dates stay null, `needs_review=true` |

### 6.3 The flagship fixture test — `test_intro_to_networks.py`

The real uploaded syllabus, run through the offline extractor, asserting on ground truth I read
out of the actual document:

- course code `CMP 405/743` recognized as **one** cross-listed course, not two
- instructor `Matthew P. Johnson`, term `Spring 2026`, institution Lehman College
- gradeable items found: ~4 programming assignments (40%), participation (10%),
  midterm (20%), final (30%) — **and the weights sum to 100**
- **no fabricated dates**: with inference disabled, every `due_date` is `null` and every task is
  `needs_review=true`
- with inference enabled and a term calendar supplied, all tasks get dates, all tagged `inferred`
- golden-JSON snapshot comparison, so a prompt or scoring tweak that shifts output is *visible*
  in the diff instead of silently landing

This one file is the regression net for the hardest realistic case we have.

### 6.4 Overlap & recommendations

| Test | Asserts |
|---|---|
| `test_overlap_detects_crunch` | synthetic 3-majors-in-one-week → `critical` window |
| `test_overlap_rolling_window` | Fri paper + Mon/Tue exams → caught by rolling window (ISO weeks miss it) |
| `test_overlap_quiet_week` | one small quiz → no window emitted (no false alarms) |
| `test_recommend_start_early` | triggered for the heaviest task in a critical window |
| `test_subtask_offsets_valid` | all `days_before` positive and inside the parent's lead time |

### 6.5 API integration (`TestClient`)

| Test | Asserts |
|---|---|
| `test_upload_pdf_endpoint` | real fixture PDF, Gemini mocked → 200 + valid contract JSON |
| `test_scan_endpoint` | synthetic JPEG page → 200, `path="vision"` |
| `test_scan_multi_page` | 3 frames → one merged course, tasks from all pages |
| `test_reject_non_pdf` | `.exe` upload → 400, clear error |
| `test_reject_oversize` | > 20 MB → 413 |
| `test_analyze_multi_course` | tasks from 3 courses → cross-course windows |

### 6.6 Eval harness (`eval/run_eval.py`)

Not a pass/fail test — a **measurement**, run manually against the real API when tuning prompts.
Hand-labeled ground truth per fixture; reports task-level precision/recall/F1, date accuracy,
type-classification accuracy, and Gemini vs. regex-baseline deltas. This is what turns prompt
iteration from vibes into evidence, and it's the artifact that makes this a defensible *ML* project
in a demo rather than an API call with a UI on it.

```bash
uv run pytest ml/tests -v          # full suite, no key, no network
uv run python eval/run_eval.py     # needs GEMINI_API_KEY
uv run python ml/wsgi.py           # then open http://127.0.0.1:5001
```

---

## 7. Milestones

| # | Deliverable | Est. |
|---|---|---|
| 1 | Scaffold: `uv` env, `pyproject`, `schemas.py` (contract frozen, shared with team) | 45m |
| 2 | Ingest + router + PDF fixture test passing | 1h |
| 3 | Offline fallback extractor + flagship fixture test | 1.5h |
| 4 | Gemini client, prompts, structured output, mocked contract tests | 2h |
| 5 | Normalize: dates, inference, dedupe, priority | 1.5h |
| 6 | OpenCV camera preprocessing + CV tests | 1.5h |
| 7 | Overlap detection + recommendations + tests | 1.5h |
| 8 | FastAPI routes + demo page (two buttons) + integration tests | 1.5h |
| 9 | Eval harness + labeled set | 1h |

Ordering is deliberate: **the fallback extractor and its tests land before the Gemini integration**,
so there is a working, demoable, testable pipeline before anything depends on a network call or an
API key. If the key or quota dies during the demo, the project still runs.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Syllabus has no dates (**confirmed in our fixture**) | null-date support + explicit inference stage, both tested |
| Gemini hallucinates plausible-but-wrong dates | `temperature=0`, explicit "return null" instruction, `source_quote` provenance, `needs_review` flag |
| Blurry camera shots waste API calls | Laplacian blur gate rejects before the call |
| Rate limits / quota exhaustion mid-demo | retry with backoff → offline extractor → cached `/api/demo/sample` |
| Schema drift breaks teammates | contract frozen at milestone 1, golden JSON in repo, snapshot test guards it |
| Model version changes behavior | model name is env-configurable; golden test surfaces the diff |
| Scanned-image PDF (no text layer) | routing heuristic sends it down the vision path automatically |

---

## 9. Decisions I made (flag if you disagree)

1. **Python 3.12 via `uv`**, not system 3.9.6 — several deps have dropped 3.9.
   (`cryptography` is pinned `<47` for Intel macOS only, by platform marker — the newest
   release has no x86_64 wheel and would force an OpenSSL source build.)
2. **`gemini-2.5-flash`** default, env-swappable — extraction is structured, not reasoning-heavy.
3. **Two endpoints, not one** — camera and file paths differ in preprocessing and failure modes.
   Shipped as a **Flask Blueprint** to match the backend, rather than a separate FastAPI service.
4. **Priority is deterministic, not model-generated** — testable, explainable, no cost, no drift.
5. **In-memory storage behind a `Repository` protocol** — matches "enough to test, link later."
6. **Term start/end is an optional request parameter** with a per-term default; without it,
   undated tasks stay undated rather than getting invented dates.

## 10. Answered

- **Backend is Flask.** The service ships as a Blueprint registered on the backend's own app,
  so there is no second process and no cross-service hop.
- **No `GEMINI_API_KEY` yet.** Everything runs without one on the offline extractor; paste a key
  into `.env` and the pipeline routes through Gemini with no other change.

---

## 11. What implementation changed

The plan survived contact with the code, with seven corrections worth recording — five of them
found by tests or by profiling, not by reading.

| # | Found | Change |
|---|---|---|
| 1 | The fixture renders `final` as `ﬁnal` (U+FB01 **ligature**) | NFKC normalization in the ingest layer. Without it a plain `/final/` regex silently drops a 30%-of-grade exam. |
| 2 | Participation is 10% of the grade but has no deadline | Excluded from tasks (you can't *complete* participation) and tracked as `meta.non_task_weight`, so `tasks + non_task = 100%` proves the grading table was parsed whole rather than partly dropped. |
| 3 | `fuzz.token_sort_ratio("Assignment 1", "Assignment 2")` = **96** | Dedupe collapsed all four programming assignments into one. Numbered titles with differing numbers are now never duplicates. |
| 4 | A 25%-of-grade overdue paper scored 0.747, just under the 0.75 cutoff | Overdue-and-incomplete is now an explicit **escalation to critical**, not an arithmetic outcome. |
| 5 | A lone project emitted a "high-workload period" | A window needs **≥2 tasks** to be flagged. This is overlap detection; highlighting every single deadline trains students to ignore the highlighting. |
| 6 | Profiling: `fastNlMeansDenoising` cost **2,918 ms of a 3,000 ms** camera pipeline | Swapped for `bilateralFilter` (52 ms) — also the better choice for text, since it preserves glyph-stroke edges instead of smoothing across them. Camera scan went **7.9 s → 0.8 s** for two pages. |
| 7 | Breakdowns spanned the whole lead time — *"start reading the spec 100 days early"* | Capped to a realistic working span per work type (paper 21d, project 28d, default 14d). |

Also added beyond the plan: `PATCH /api/tasks/<id>` (mark complete / correct a bad extraction),
because the `needs_review` design is only half a feature without a way for the student to act on it.

---

## 12. Verified end to end

Against a live server, not just the test client:

| Check | Result |
|---|---|
| `POST /api/syllabus/upload` — the real 3-page syllabus | **200** in 98 ms · 6 tasks · weights total 100% |
| `POST /api/syllabus/scan` — 2 tilted, unevenly-lit simulated photos | **200** in 801 ms · both pages accepted · `corrected -5.5deg skew` |
| Blurry photo | **422** `{"reason":"too_blurry","retake":true}` — rejected *before* any model call |
| `.exe` to the upload button | **400** "not a PDF. Use the camera button for photos." |
| PDF to the camera button | **400** "unsupported image type" |
| `PATCH /api/tasks/<id>` with a corrected date | `date_source` → `explicit`, `needs_review` → `false` |
| `POST /api/analyze` — 3 courses colliding in one week | one **critical** window, load 17.5, with a start-early plan |
| **Invalid** Gemini key (real 400 from Google) | **200** — classified non-retryable, degraded to the offline extractor, all 6 tasks still returned |

The last row is the one that matters for demo day: a dead or rate-limited key costs a log warning,
not a broken product.
