# Syllabus Intelligence Engine — ML/AI track

Turns a syllabus (PDF **or** camera photo) into structured, prioritized,
conflict-analyzed academic tasks.

Design doc: [`docs/ML_PLAN.md`](../docs/ML_PLAN.md)

---

## Setup — one step

```bash
uv sync                       # creates .venv with Python 3.12
```

That's it. **It runs with no API key**, using the offline regex extractor.

### Adding Gemini

Paste your key into `.env` (already created, gitignored) and restart:

```
GEMINI_API_KEY=your-key-here
```

Get one at <https://aistudio.google.com/apikey>. Nothing else changes — the
pipeline detects the key at startup and routes extraction through Gemini
instead of the regex baseline. `GET /api/health` tells you which one is live.

If the key is missing, invalid, rate-limited, or the API is down, the pipeline
**degrades to the offline extractor and still returns a full result.** A dead
key costs a warning in the log, not a broken demo.

---

## Run it

```bash
uv run python ml/wsgi.py          # http://127.0.0.1:5001
```

Open <http://127.0.0.1:5001> for the demo harness: two buttons, a task table,
crunch-week highlighting, and the raw JSON.

```bash
uv run pytest ml/tests -q                 # 123 tests, no key, no network
uv run python ml/eval/run_eval.py         # score the extractor vs. ground truth
uv run python ml/eval/run_eval.py --gemini   # ...and vs. Gemini (needs a key)
uv run python ml/scripts/make_golden.py   # regenerate the snapshot (read the diff!)
```

---

## How to test it

Four levels, cheapest first.

**1. The suite — proves the plumbing.** 123 tests, no key, no network, ~5s.
```bash
uv run pytest ml/tests -q
```

**2. A syllabus it has never seen — proves it generalizes.** The fixture is a
regression net; it says nothing about a new document. This is the test that
actually tells you whether the thing works.
```bash
uv run python ml/scripts/try_syllabus.py ~/Downloads/some_syllabus.pdf
uv run python ml/scripts/try_syllabus.py page1.jpg page2.jpg     # camera path
uv run python ml/scripts/try_syllabus.py syllabus.pdf --no-infer # raw extraction
```
Read the **PROVENANCE** block in the output. Every task shows the exact quote it
came from — if a quote doesn't support its task, that's a real bug, and it's
visible without reading any code.

Also run it on something that is **not** a syllabus. The correct answer is zero
tasks, not invented ones.

**3. Numbers, not vibes.** Hand-label a syllabus in `eval/labels/`, then:
```bash
uv run python ml/eval/run_eval.py            # regex baseline
uv run python ml/eval/run_eval.py --gemini   # ...vs the model
```
Watch the `halluc` column: dates invented for undated items. It must stay 0.

**4. The demo page — the human check.**
```bash
uv run python ml/wsgi.py     # http://127.0.0.1:5001
```

### What cannot be tested without a key

**The camera path only half-works offline.** CV preprocessing (deskew,
perspective, blur gate) runs and is tested — but the offline extractor has no
OCR, so with no key a photo yields zero tasks. Reading pixels requires the
vision model. Add `GEMINI_API_KEY` before judging the camera button.

---

## Wiring it into the Flask backend

The service is a **Blueprint**, so it drops into the existing app — no second
process, no cross-service HTTP hop:

```python
from ml.app.routes import syllabus_bp
app.register_blueprint(syllabus_bp)          # adds everything under /api
```

Persistence is behind a `Protocol` in [`app/storage.py`](app/storage.py). Swap
the in-memory implementation for a real one:

```python
class PostgresRepository:          # implement these six methods
    def save_result(self, result): ...
    def all_tasks(self): ...
    def get_task(self, task_id): ...
    def update_task(self, task_id, changes): ...
    def courses(self): ...
    def clear(self): ...

app.extensions["syllabus_repo"] = PostgresRepository(...)
```

Nothing else in the pipeline changes.

### Endpoints

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | liveness + which extractor is active |
| `POST` | `/api/syllabus/upload` | **file-upload button** — multipart `file` (PDF) |
| `POST` | `/api/syllabus/scan` | **camera button** — multipart `images` (1..12 frames) |
| `POST` | `/api/analyze` | cross-course overlap for the union of all tasks |
| `GET` | `/api/tasks` | list stored tasks |
| `PATCH` | `/api/tasks/<id>` | mark complete / correct a wrong extraction |
| `GET` | `/api/demo/sample` | golden output, no key and no upload needed |

All four extraction/analysis routes accept optional `term_start`, `term_end`,
`today` (all `YYYY-MM-DD`) and `infer_dates` (`true`/`false`).

Response shape is fixed by [`app/schemas.py`](app/schemas.py) — that file is the
contract. A live example is in
[`tests/fixtures/golden/intro_to_networks.json`](tests/fixtures/golden/intro_to_networks.json);
build the frontend against it.

---

## What to know before changing things

**Dates are never guessed.** The flagship fixture syllabus contains zero dates.
`due_date: null` is a valid result, and any date we place ourselves is tagged
`date_source: "inferred"` with `needs_review: true`. A confidently wrong date is
worse than an empty one — several tests exist purely to enforce this.

**Priority is arithmetic, not a model call.** See `normalize/priority.py`. It's
testable, explainable (`priority_reason` on every task), free, and doesn't drift
when a model version changes.

**Only stage 4 is non-deterministic.** Everything else is pure functions, which
is why the test suite means something. Mock the model at the
`pipeline.extract_from_*` boundary — see the `fake_gemini` fixture.

**The regex extractor is not a stub.** It's the CI extractor, the degraded-mode
path, and the baseline Gemini is measured against in `eval/`. Keep it working.

**Regenerating the golden snapshot is a deliberate act.** Read the diff. That
diff is the only thing standing between a prompt tweak and silent drift.
