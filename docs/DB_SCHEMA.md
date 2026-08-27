# Database schema — column reference

Executable migration: [`migrations/001_initial_schema.sql`](../migrations/001_initial_schema.sql) · Contract source: [`ml/app/schemas.py`](../ml/app/schemas.py)

5 tables · 76 columns · PostgreSQL. Every column below is either a field the ML
pipeline returns or a field the backend needs to manage the upload lifecycle.

---

## Enum types

| Type | Values |
|---|---|
| `upload_source` | `file` · `camera` |
| `upload_status` | `pending` · `processing` · `succeeded` · `failed` · `needs_retake` |
| `pipeline_path` | `native_text` · `vision` · `hybrid` · `fallback` |
| `date_source` | `explicit` · `inferred` · `unknown` |
| `task_priority` | `critical` · `high` · `medium` · `low` |
| `task_type` | `assignment` · `quiz` · `exam` · `midterm` · `final` · `project` · `paper` · `presentation` · `reading` · `other` |

---

## 1. `syllabus_uploads` — 25 columns

Both buttons write here. `source` is the discriminator.

| Column | Type | Null | Default | Notes |
|---|---|:--:|---|---|
| `id` | `uuid` | no | `gen_random_uuid()` | PK |
| `user_id` | `uuid` | no | — | FK → `users(id)` ON DELETE CASCADE |
| `source` | `upload_source` | no | — | **`file` or `camera`** — which button |
| `original_filename` | `text` | **yes** | — | file uploads only; camera has none |
| `mime_type` | `text` | no | — | `application/pdf`, `image/jpeg`, … |
| `byte_size` | `integer` | no | — | bytes; reject > 20 MB |
| `storage_key` | `text` | no | — | S3/disk pointer to the **original** bytes |
| `content_sha256` | `char(64)` | no | — | hash of raw bytes; dedupes re-uploads |
| `page_count` | `integer` | no | `0` | PDF pages, or camera frames |
| `status` | `upload_status` | no | `'pending'` | lifecycle |
| `error_code` | `text` | **yes** | — | `too_blurry`, `no_document_found`, `not_a_pdf` |
| `error_message` | `text` | **yes** | — | human-readable, shown to the student |
| `pipeline_path` | `pipeline_path` | **yes** | — | `meta.pipeline_path` |
| `model` | `text` | **yes** | — | `gemini-2.5-flash` or `offline-regex` |
| `processing_ms` | `integer` | **yes** | — | `meta.processing_ms` |
| `warnings` | `jsonb` | no | `'[]'` | array of strings, `meta.warnings` |
| `non_task_weight` | `numeric(5,2)` | **yes** | — | graded but undeadlined (participation) |
| `grade_weight_total` | `numeric(5,2)` | **yes** | — | should reach `100.00` |
| `term_start` | `date` | **yes** | — | request param, for reproducibility |
| `term_end` | `date` | **yes** | — | request param |
| `infer_dates` | `boolean` | no | `true` | request param |
| `extraction_json` | `jsonb` | **yes** | — | full `ExtractionResult`; backfill insurance |
| `course_id` | `uuid` | **yes** | — | FK → `courses(id)` ON DELETE SET NULL |
| `created_at` | `timestamptz` | no | `now()` | |
| `updated_at` | `timestamptz` | no | `now()` | |

**Indexes**
```sql
UNIQUE (user_id, content_sha256)                      -- skip duplicate extractions
INDEX  (user_id, created_at DESC)                     -- upload history
INDEX  (status) WHERE status IN ('pending','processing')  -- the work queue
CHECK  (source <> 'camera' OR original_filename IS NULL)
```

---

## 2. `syllabus_upload_pages` — 11 columns

One row per camera frame or rasterized PDF page. This is where the two paths
genuinely diverge: per-page quality metrics enable per-page retake.

| Column | Type | Null | Default | Notes |
|---|---|:--:|---|---|
| `id` | `uuid` | no | `gen_random_uuid()` | PK |
| `upload_id` | `uuid` | no | — | FK → `syllabus_uploads(id)` ON DELETE CASCADE |
| `page_number` | `integer` | no | — | 1-indexed |
| `storage_key` | `text` | **yes** | — | the **preprocessed** image actually sent to the model |
| `blur_score` | `real` | **yes** | — | Laplacian variance; `< 45` is rejected |
| `document_found` | `boolean` | **yes** | — | was a page border detected |
| `skew_corrected_deg` | `real` | **yes** | — | degrees rotated to level the text |
| `accepted` | `boolean` | no | `true` | `false` = dropped before any model call |
| `warnings` | `jsonb` | no | `'[]'` | per-page warnings |
| `extracted_chars` | `integer` | **yes** | — | native-text path only; null for camera |
| `created_at` | `timestamptz` | no | `now()` | |

**Index:** `UNIQUE (upload_id, page_number)`

---

## 3. `courses` — 10 columns

| Column | Type | Null | Default | Notes |
|---|---|:--:|---|---|
| `id` | `uuid` | no | `gen_random_uuid()` | PK |
| `user_id` | `uuid` | no | — | FK → `users(id)` ON DELETE CASCADE |
| `code` | `text` | no | — | `CMP 405/743` — cross-listed stays **one** course |
| `name` | `text` | no | — | `Intro to Networks` |
| `institution` | `text` | **yes** | — | `Lehman College, CUNY` |
| `term` | `text` | **yes** | — | `Spring 2026` |
| `instructor` | `text` | **yes** | — | |
| `meeting_times` | `text` | **yes** | — | |
| `confidence` | `real` | no | `0.5` | 0.0–1.0 |
| `created_at` | `timestamptz` | no | `now()` | |

**Index:** `UNIQUE (user_id, code, term)`

---

## 4. `tasks` — 23 columns

The to-do list. This is what the frontend renders.

| Column | Type | Null | Default | Notes |
|---|---|:--:|---|---|
| `id` | `uuid` | no | `gen_random_uuid()` | PK |
| `user_id` | `uuid` | no | — | FK → `users(id)` ON DELETE CASCADE |
| `course_id` | `uuid` | no | — | FK → `courses(id)` ON DELETE CASCADE |
| `upload_id` | `uuid` | **yes** | — | FK → `syllabus_uploads(id)`; which syllabus produced it |
| `title` | `text` | no | — | `Programming Assignment 3` |
| `type` | `task_type` | no | — | |
| `due_date` | `date` | **yes** | — | **NULL is valid and common** |
| `due_time` | `time` | **yes** | — | |
| `date_source` | `date_source` | no | `'unknown'` | render `inferred` differently |
| `needs_review` | `boolean` | no | `false` | prompt the student to confirm |
| `confidence` | `real` | no | `0.5` | rank what to ask about first |
| `grade_pct` | `numeric(5,2)` | **yes** | — | 0–100 |
| `priority` | `task_priority` | no | `'medium'` | |
| `priority_score` | `real` | no | `0` | 0.0–1.0, for sorting |
| `priority_reason` | `text` | no | `''` | shown in UI; makes "critical" explainable |
| `estimated_hours` | `integer` | **yes** | — | |
| `completed` | `boolean` | no | `false` | |
| `completed_at` | `timestamptz` | **yes** | — | |
| `source_page` | `integer` | **yes** | — | provenance |
| `source_quote` | `text` | no | `''` | verbatim span from the syllabus |
| `user_edited` | `boolean` | no | `false` | re-extraction must not clobber a correction |
| `created_at` | `timestamptz` | no | `now()` | |
| `updated_at` | `timestamptz` | no | `now()` | |

**Indexes**
```sql
INDEX (user_id, due_date) WHERE completed = false   -- the main list query
INDEX (user_id)           WHERE needs_review = true -- the "confirm these" queue
INDEX (course_id)
```

---

## 5. `subtasks` — 7 columns

AI-generated breakdown of a large deliverable.

| Column | Type | Null | Default | Notes |
|---|---|:--:|---|---|
| `id` | `uuid` | no | `gen_random_uuid()` | PK |
| `task_id` | `uuid` | no | — | FK → `tasks(id)` ON DELETE CASCADE |
| `title` | `text` | no | — | `Write a full draft` |
| `days_before` | `integer` | no | — | `CHECK (days_before >= 1)` |
| `due_date` | `date` | **yes** | — | `parent.due_date - days_before` |
| `completed` | `boolean` | no | `false` | |
| `position` | `integer` | no | `0` | display order |

---

## Deliberately not stored

`workload_analysis.windows` and `recommendations`. Both are derived from the
**current** task set across **all** courses, so they go stale the instant a task
is completed, edited, or another syllabus is added. Recompute by POSTing the
user's tasks to `/api/analyze`.

If you later cache them for push notifications, add a `computed_at` and
invalidate on any task write — but never treat the cache as source of truth.
