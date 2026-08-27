-- 001_initial_schema.sql — Syllabus Intelligence Engine
--
-- Apply with:
--   psql -h 127.0.0.1 -U <user> -d syllabus_planner -f migrations/001_initial_schema.sql
--
-- Column reference: docs/DB_SCHEMA.md
-- Contract source:  ml/app/schemas.py
--
-- Creation order matters: courses before syllabus_uploads (which FKs to it),
-- syllabus_uploads before tasks. Wrapped in a transaction so a partial apply
-- rolls back rather than leaving half a schema behind.

BEGIN;

-- ---------------------------------------------------------------------------
-- Enum types
-- ---------------------------------------------------------------------------
CREATE TYPE upload_source AS ENUM ('file', 'camera');
CREATE TYPE upload_status AS ENUM ('pending', 'processing', 'succeeded', 'failed', 'needs_retake');
CREATE TYPE pipeline_path AS ENUM ('native_text', 'vision', 'hybrid', 'fallback');
CREATE TYPE date_source   AS ENUM ('explicit', 'inferred', 'unknown');
CREATE TYPE task_priority AS ENUM ('critical', 'high', 'medium', 'low');
CREATE TYPE task_type     AS ENUM ('assignment', 'quiz', 'exam', 'midterm', 'final',
                                   'project', 'paper', 'presentation', 'reading', 'other');

-- ---------------------------------------------------------------------------
-- users — PLACEHOLDER
-- ---------------------------------------------------------------------------
-- Minimal on purpose. Auth belongs to whoever owns the backend; this exists so
-- the foreign keys below resolve. Extend it (or replace it and re-point the
-- FKs) when real auth lands -- just keep the `id uuid` primary key.
CREATE TABLE users (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email      text UNIQUE NOT NULL,
    name       text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- courses
-- ---------------------------------------------------------------------------
CREATE TABLE courses (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code          text NOT NULL,          -- 'CMP 405/743' — cross-listed stays ONE course
    name          text NOT NULL,
    institution   text,
    term          text,                   -- 'Spring 2026'
    instructor    text,
    meeting_times text,
    confidence    real NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, code, term)
);

-- ---------------------------------------------------------------------------
-- syllabus_uploads — BOTH buttons land here; `source` is the discriminator
-- ---------------------------------------------------------------------------
CREATE TABLE syllabus_uploads (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    source             upload_source NOT NULL,          -- 'file' | 'camera'
    original_filename  text,                            -- file uploads only
    mime_type          text NOT NULL,
    byte_size          integer NOT NULL CHECK (byte_size > 0),

    storage_key        text NOT NULL,                   -- pointer to the ORIGINAL bytes
    content_sha256     char(64) NOT NULL,               -- dedupes re-uploads
    page_count         integer NOT NULL DEFAULT 0,

    status             upload_status NOT NULL DEFAULT 'pending',
    error_code         text,
    error_message      text,

    -- ExtractionResult.meta
    pipeline_path      pipeline_path,
    model              text,
    processing_ms      integer,
    warnings           jsonb NOT NULL DEFAULT '[]'::jsonb,
    non_task_weight    numeric(5,2),
    grade_weight_total numeric(5,2),

    -- request parameters, so a run is reproducible
    term_start         date,
    term_end           date,
    infer_dates        boolean NOT NULL DEFAULT true,

    extraction_json    jsonb,
    course_id          uuid REFERENCES courses(id) ON DELETE SET NULL,

    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT filename_only_for_file_uploads
        CHECK (source <> 'camera' OR original_filename IS NULL),
    CONSTRAINT term_range_is_ordered
        CHECK (term_start IS NULL OR term_end IS NULL OR term_start <= term_end)
);

CREATE UNIQUE INDEX uploads_user_content_uniq ON syllabus_uploads (user_id, content_sha256);
CREATE INDEX uploads_user_created ON syllabus_uploads (user_id, created_at DESC);
CREATE INDEX uploads_pending      ON syllabus_uploads (status)
    WHERE status IN ('pending', 'processing');

-- ---------------------------------------------------------------------------
-- syllabus_upload_pages — one row per camera frame / rasterized PDF page
-- ---------------------------------------------------------------------------
CREATE TABLE syllabus_upload_pages (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id          uuid NOT NULL REFERENCES syllabus_uploads(id) ON DELETE CASCADE,
    page_number        integer NOT NULL CHECK (page_number >= 1),

    storage_key        text,               -- the PREPROCESSED image sent to the model
    blur_score         real,               -- Laplacian variance; < 45 is rejected
    document_found     boolean,
    skew_corrected_deg real,
    accepted           boolean NOT NULL DEFAULT true,
    warnings           jsonb NOT NULL DEFAULT '[]'::jsonb,
    extracted_chars    integer,            -- native-text path only

    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (upload_id, page_number)
);

-- ---------------------------------------------------------------------------
-- tasks — the to-do list
-- ---------------------------------------------------------------------------
CREATE TABLE tasks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id       uuid NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    upload_id       uuid REFERENCES syllabus_uploads(id) ON DELETE SET NULL,

    title           text NOT NULL,
    type            task_type NOT NULL,

    due_date        date,                  -- NULL is valid and common. Keep it nullable.
    due_time        time,

    date_source     date_source NOT NULL DEFAULT 'unknown',
    needs_review    boolean NOT NULL DEFAULT false,
    confidence      real NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),

    grade_pct       numeric(5,2) CHECK (grade_pct IS NULL OR grade_pct BETWEEN 0 AND 100),
    priority        task_priority NOT NULL DEFAULT 'medium',
    priority_score  real NOT NULL DEFAULT 0,
    priority_reason text NOT NULL DEFAULT '',
    estimated_hours integer,

    completed       boolean NOT NULL DEFAULT false,
    completed_at    timestamptz,

    source_page     integer,
    source_quote    text NOT NULL DEFAULT '',

    user_edited     boolean NOT NULL DEFAULT false,

    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),

    -- Keeps the completion flag and its timestamp from drifting apart.
    CONSTRAINT completed_at_matches_completed
        CHECK ((completed = false AND completed_at IS NULL)
            OR (completed = true  AND completed_at IS NOT NULL))
);

CREATE INDEX tasks_user_due     ON tasks (user_id, due_date) WHERE completed = false;
CREATE INDEX tasks_needs_review ON tasks (user_id)           WHERE needs_review = true;
CREATE INDEX tasks_course       ON tasks (course_id);
CREATE INDEX tasks_upload       ON tasks (upload_id);

-- ---------------------------------------------------------------------------
-- subtasks — AI-generated breakdown of a large deliverable
-- ---------------------------------------------------------------------------
CREATE TABLE subtasks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id     uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    title       text NOT NULL,
    days_before integer NOT NULL CHECK (days_before >= 1),
    due_date    date,
    completed   boolean NOT NULL DEFAULT false,
    position    integer NOT NULL DEFAULT 0
);

CREATE INDEX subtasks_task ON subtasks (task_id, position);

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------
-- In the DB rather than the app, so a stray UPDATE from psql or a background
-- job can't leave a stale timestamp behind.
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER uploads_touch BEFORE UPDATE ON syllabus_uploads
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER tasks_touch BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

COMMIT;
