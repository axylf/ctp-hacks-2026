BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typname = 'date_source'
    ) THEN
        CREATE TYPE public.date_source AS ENUM ('explicit', 'inferred', 'unknown');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typname = 'pipeline_path'
    ) THEN
        CREATE TYPE public.pipeline_path AS ENUM ('native_text', 'vision', 'hybrid', 'fallback');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typname = 'task_priority'
    ) THEN
        CREATE TYPE public.task_priority AS ENUM ('critical', 'high', 'medium', 'low');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typname = 'task_type'
    ) THEN
        CREATE TYPE public.task_type AS ENUM ('assignment', 'quiz', 'exam', 'midterm', 'final', 'project', 'paper', 'presentation', 'reading', 'other');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typname = 'upload_source'
    ) THEN
        CREATE TYPE public.upload_source AS ENUM ('file', 'camera');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typname = 'upload_status'
    ) THEN
        CREATE TYPE public.upload_status AS ENUM ('pending', 'processing', 'succeeded', 'failed', 'needs_retake');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE,
    name text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.courses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    code text NOT NULL,
    name text NOT NULL,
    institution text,
    term text,
    instructor text,
    meeting_times text,
    confidence real NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, code, term)
);

CREATE TABLE IF NOT EXISTS public.syllabus_uploads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    source public.upload_source NOT NULL,
    original_filename text,
    mime_type text NOT NULL,
    byte_size integer NOT NULL CHECK (byte_size > 0),
    storage_key text NOT NULL,
    content_sha256 character(64) NOT NULL,
    page_count integer NOT NULL DEFAULT 0,
    status public.upload_status NOT NULL DEFAULT 'pending',
    error_code text,
    error_message text,
    pipeline_path public.pipeline_path,
    model text,
    processing_ms integer,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    non_task_weight numeric(5,2),
    grade_weight_total numeric(5,2),
    term_start date,
    term_end date,
    infer_dates boolean NOT NULL DEFAULT true,
    extraction_json jsonb,
    course_id uuid REFERENCES public.courses(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source <> 'camera' OR original_filename IS NULL),
    CHECK (term_start IS NULL OR term_end IS NULL OR term_start <= term_end)
);

CREATE TABLE IF NOT EXISTS public.syllabus_upload_pages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id uuid NOT NULL REFERENCES public.syllabus_uploads(id) ON DELETE CASCADE,
    page_number integer NOT NULL CHECK (page_number >= 1),
    storage_key text,
    blur_score real,
    document_found boolean,
    skew_corrected_deg real,
    accepted boolean NOT NULL DEFAULT true,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    extracted_chars integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (upload_id, page_number)
);

CREATE TABLE IF NOT EXISTS public.tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    course_id uuid NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    upload_id uuid REFERENCES public.syllabus_uploads(id) ON DELETE SET NULL,
    title text NOT NULL,
    type public.task_type NOT NULL,
    due_date date,
    due_time time,
    date_source public.date_source NOT NULL DEFAULT 'unknown',
    needs_review boolean NOT NULL DEFAULT false,
    confidence real NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    grade_pct numeric(5,2) CHECK (grade_pct IS NULL OR (grade_pct >= 0 AND grade_pct <= 100)),
    priority public.task_priority NOT NULL DEFAULT 'medium',
    priority_score real NOT NULL DEFAULT 0,
    priority_reason text NOT NULL DEFAULT '',
    estimated_hours integer,
    completed boolean NOT NULL DEFAULT false,
    completed_at timestamptz,
    source_page integer,
    source_quote text NOT NULL DEFAULT '',
    user_edited boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((completed = false AND completed_at IS NULL) OR (completed = true AND completed_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS public.subtasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    title text NOT NULL,
    days_before integer NOT NULL CHECK (days_before >= 1),
    due_date date,
    completed boolean NOT NULL DEFAULT false,
    position integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS subtasks_task ON public.subtasks (task_id, position);
CREATE INDEX IF NOT EXISTS tasks_course ON public.tasks (course_id);
CREATE INDEX IF NOT EXISTS tasks_needs_review ON public.tasks (user_id) WHERE needs_review = true;
CREATE INDEX IF NOT EXISTS tasks_upload ON public.tasks (upload_id);
CREATE INDEX IF NOT EXISTS tasks_user_due ON public.tasks (user_id, due_date) WHERE completed = false;
CREATE INDEX IF NOT EXISTS uploads_pending ON public.syllabus_uploads (status) WHERE status IN ('pending', 'processing');
CREATE UNIQUE INDEX IF NOT EXISTS uploads_user_content_uniq ON public.syllabus_uploads (user_id, content_sha256);
CREATE INDEX IF NOT EXISTS uploads_user_created ON public.syllabus_uploads (user_id, created_at DESC);

DROP TRIGGER IF EXISTS tasks_touch ON public.tasks;
DROP TRIGGER IF EXISTS uploads_touch ON public.syllabus_uploads;
DROP FUNCTION IF EXISTS public.touch_updated_at();

CREATE OR REPLACE FUNCTION public.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER tasks_touch
BEFORE UPDATE ON public.tasks
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER uploads_touch
BEFORE UPDATE ON public.syllabus_uploads
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

INSERT INTO public.users (id, email, name)
VALUES
    ('11111111-1111-4111-8111-111111111111', 'alex@example.com', 'Alex Chen'),
    ('22222222-2222-4222-8222-222222222222', 'maria@example.com', 'Maria Patel'),
    ('33333333-3333-4333-8333-333333333333', 'jordan@example.com', 'Jordan Lee'),
    ('44444444-4444-4444-8444-444444444444', 'sophia@example.com', 'Sophia Nguyen'),
    ('55555555-5555-4555-8555-555555555555', 'liam@example.com', 'Liam Brooks')
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.courses (id, user_id, code, name, institution, term, instructor, meeting_times, confidence)
VALUES
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', '11111111-1111-4111-8111-111111111111', 'CS101', 'Intro to Computer Science', 'Northwest University', 'Fall 2026', 'Dr. Morgan Reed', 'MWF 9:00-10:00', 0.92),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '22222222-2222-4222-8222-222222222222', 'BIO210', 'Cell Biology', 'Northwest University', 'Fall 2026', 'Dr. Evelyn Cross', 'TR 11:00-12:30', 0.88),
    ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', '33333333-3333-4333-8333-333333333333', 'ENG205', 'Rhetoric and Writing', 'Bayview College', 'Fall 2026', 'Prof. Aaron Silva', 'MW 1:00-2:30', 0.9),
    ('dddddddd-dddd-4ddd-8ddd-dddddddddddd', '44444444-4444-4444-8444-444444444444', 'MATH220', 'Discrete Mathematics', 'Bayview College', 'Fall 2026', 'Dr. Hannah Wu', 'TR 9:30-11:00', 0.94),
    ('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', '55555555-5555-4555-8555-555555555555', 'HIST150', 'Modern World History', 'Northwest University', 'Fall 2026', 'Prof. Daniel Ortiz', 'F 10:00-12:00', 0.85)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.syllabus_uploads (
    id, user_id, source, original_filename, mime_type, byte_size, storage_key,
    content_sha256, page_count, status, pipeline_path, model, processing_ms,
    warnings, term_start, term_end, infer_dates, extraction_json, course_id
)
VALUES
    (
        '10000000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'file', 'cs101_fall_2026.pdf', 'application/pdf', 184200,
        'syllabi/11111111-1111-4111-8111-111111111111/cs101_fall_2026.pdf',
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 1, 'succeeded', 'native_text', 'tesseract', 2140,
        '[]'::jsonb, '2026-08-25', '2026-12-18', true,
        '{"raw_text":"CS101: Intro to Computer Science syllabus...","pages":[{"page_number":1,"text":"CS101: Intro to Computer Science syllabus..."}]}'::jsonb,
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    ),
    (
        '10000000-0000-4000-8000-000000000002', '22222222-2222-4222-8222-222222222222', 'file', 'bio210_syllabus.pdf', 'application/pdf', 203400,
        'syllabi/22222222-2222-4222-8222-222222222222/bio210_syllabus.pdf',
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 1, 'processing', 'vision', 'gpt-4o-mini', 3125,
        '[]'::jsonb, '2026-08-24', '2026-12-17', true,
        '{"raw_text":"BIO210: Cell Biology syllabus...","pages":[{"page_number":1,"text":"BIO210: Cell Biology syllabus..."}]}'::jsonb,
        'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    ),
    (
        '10000000-0000-4000-8000-000000000003', '33333333-3333-4333-8333-333333333333', 'file', 'eng205_writing.pdf', 'application/pdf', 175000,
        'syllabi/33333333-3333-4333-8333-333333333333/eng205_writing.pdf',
        'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', 1, 'succeeded', 'hybrid', 'tesseract', 2870,
        '[]'::jsonb, '2026-08-27', '2026-12-20', true,
        '{"raw_text":"ENG205: Rhetoric and Writing syllabus...","pages":[{"page_number":1,"text":"ENG205: Rhetoric and Writing syllabus..."}]}'::jsonb,
        'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
    ),
    (
        '10000000-0000-4000-8000-000000000004', '44444444-4444-4444-8444-444444444444', 'file', 'math220_schedule.pdf', 'application/pdf', 226800,
        'syllabi/44444444-4444-4444-8444-444444444444/math220_schedule.pdf',
        'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', 1, 'failed', 'fallback', 'ocr-space', 1760,
        '["low contrast detected"]'::jsonb, '2026-08-26', '2026-12-19', true,
        '{"raw_text":"MATH220: Discrete Mathematics syllabus...","pages":[{"page_number":1,"text":"MATH220: Discrete Mathematics syllabus..."}]}'::jsonb,
        'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
    ),
    (
        '10000000-0000-4000-8000-000000000005', '55555555-5555-4555-8555-555555555555', 'camera', NULL, 'image/jpeg', 96800,
        'syllabi/55555555-5555-4555-8555-555555555555/history_camera_capture.jpg',
        'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee', 1, 'needs_retake', 'native_text', 'tesseract', 1980,
        '["image was partially blurred"]'::jsonb, '2026-08-20', '2026-12-16', true,
        '{"raw_text":"HIST150: Modern World History syllabus...","pages":[{"page_number":1,"text":"HIST150: Modern World History syllabus..."}]}'::jsonb,
        'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.syllabus_upload_pages (id, upload_id, page_number, storage_key, blur_score, document_found, skew_corrected_deg, accepted, warnings, extracted_chars)
VALUES
    ('20000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', 1, 'syllabi/11111111-1111-4111-8111-111111111111/cs101_fall_2026.pdf', 0.12, true, 0.0, true, '[]'::jsonb, 1820),
    ('20000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002', 1, 'syllabi/22222222-2222-4222-8222-222222222222/bio210_syllabus.pdf', 0.18, true, 0.5, true, '[]'::jsonb, 1945),
    ('20000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000003', 1, 'syllabi/33333333-3333-4333-8333-333333333333/eng205_writing.pdf', 0.11, true, 0.0, true, '[]'::jsonb, 1470),
    ('20000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000004', 1, 'syllabi/44444444-4444-4444-8444-444444444444/math220_schedule.pdf', 0.41, true, 2.7, false, '["low contrast detected"]'::jsonb, 860),
    ('20000000-0000-4000-8000-000000000005', '10000000-0000-4000-8000-000000000005', 1, 'syllabi/55555555-5555-4555-8555-555555555555/history_camera_capture.jpg', 0.31, true, 1.2, true, '["image was partially blurred"]'::jsonb, 1290)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.tasks (
    id, user_id, course_id, upload_id, title, type, due_date, due_time, date_source,
    needs_review, confidence, grade_pct, priority, priority_score, priority_reason,
    estimated_hours, completed, completed_at, source_page, source_quote, user_edited
)
VALUES
    (
        '30000000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', '10000000-0000-4000-8000-000000000001',
        'Homework 1: Variables and IO', 'assignment', '2026-09-05', '23:59:00', 'explicit', false, 0.96, 10.00, 'high', 82.5,
        'Directly mentioned as first graded assignment', 3, false, NULL, 1, 'Variables and input/output are required for the first homework.', true
    ),
    (
        '30000000-0000-4000-8000-000000000002', '22222222-2222-4222-8222-222222222222', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '10000000-0000-4000-8000-000000000002',
        'Lab Report: Cell Signaling', 'project', '2026-09-12', '17:00:00', 'inferred', true, 0.83, 15.00, 'medium', 64.2,
        'Project has a large laboratory component and timeline pressure', 6, false, NULL, 1, 'Cell signaling is a major topic in this unit.', false
    ),
    (
        '30000000-0000-4000-8000-000000000003', '33333333-3333-4333-8333-333333333333', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', '10000000-0000-4000-8000-000000000003',
        'Essay Draft', 'paper', '2026-09-08', '14:00:00', 'explicit', false, 0.9, 20.00, 'high', 76.3,
        'Essay draft is weighted heavily and due early in the term', 5, false, NULL, 1, 'Draft due before the final analysis paper.', true
    ),
    (
        '30000000-0000-4000-8000-000000000004', '44444444-4444-4444-8444-444444444444', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', '10000000-0000-4000-8000-000000000004',
        'Quiz 2 Review Sheet', 'quiz', '2026-09-10', '08:00:00', 'explicit', true, 0.72, 12.50, 'medium', 58.7,
        'Short review window and quiz scoring matters for course grade', 2, false, NULL, 1, 'Covers sets, logic, and proofs.', false
    ),
    (
        '30000000-0000-4000-8000-000000000005', '55555555-5555-4555-8555-555555555555', 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', '10000000-0000-4000-8000-000000000005',
        'Primary Source Response', 'reading', '2026-09-14', '23:59:00', 'inferred', false, 0.87, 18.75, 'low', 43.8,
        'Reading response is listed as a recurring low-weight assignment', 1, false, NULL, 1, 'The response should cite the assigned chapter and article.', false
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.subtasks (id, task_id, title, days_before, due_date, completed, position)
VALUES
    ('40000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001', 'Read assignment prompt', 7, '2026-08-29', false, 0),
    ('40000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000002', 'Collect experimental notes', 5, '2026-09-07', false, 0),
    ('40000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000003', 'Outline thesis and sources', 4, '2026-09-04', false, 0),
    ('40000000-0000-4000-8000-000000000004', '30000000-0000-4000-8000-000000000004', 'Review proof strategies', 3, '2026-09-07', true, 0),
    ('40000000-0000-4000-8000-000000000005', '30000000-0000-4000-8000-000000000005', 'Summarize chapter themes', 2, '2026-09-12', false, 0)
ON CONFLICT (id) DO NOTHING;

COMMIT;
