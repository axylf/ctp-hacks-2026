"""Run the pipeline on the fixture syllabus and write the result to Postgres.

Two purposes:
  1. proves the schema in migrations/001_initial_schema.sql actually fits the
     contract in ml/app/schemas.py -- a schema nothing has ever been inserted
     into is a guess, not a schema
  2. it IS the reference implementation of Repository.save_result() for the
     Flask backend. The insert order and column mapping below are what a real
     PostgresRepository needs to do.

    uv run --group db python ml/scripts/seed_db.py
    uv run --group db python ml/scripts/seed_db.py --reset   # wipe rows first
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from ml.app.config import settings  # noqa: E402
from ml.app.pipeline import PipelineOptions, process_pdf  # noqa: E402
from ml.app.schemas import ExtractionResult  # noqa: E402
from ml.tests.conftest import TERM_END, TERM_START, TODAY  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[1]
           / "tests" / "fixtures" / "syllabi" / "intro_to_networks_spring2026.pdf")


def ensure_user(cur, email: str = "1179191930jing@gmail.com") -> str:
    cur.execute(
        "INSERT INTO users (email, name) VALUES (%s, %s) "
        "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id",
        (email, "Demo Student"),
    )
    return cur.fetchone()[0]


def save_result(
    cur,
    user_id: str,
    result: ExtractionResult,
    *,
    source: str,
    raw_bytes: bytes,
    mime_type: str,
    original_filename: str | None,
    storage_key: str,
    options: PipelineOptions,
) -> tuple[str, str]:
    """The reference save. Order matters: course -> upload -> pages -> tasks."""
    meta = result.meta

    # 1. course (upsert on the natural key)
    cur.execute(
        """
        INSERT INTO courses (user_id, code, name, institution, term, instructor,
                             meeting_times, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, code, term) DO UPDATE
          SET name = EXCLUDED.name,
              instructor = COALESCE(EXCLUDED.instructor, courses.instructor),
              confidence = EXCLUDED.confidence
        RETURNING id
        """,
        (user_id, result.course.code, result.course.name, result.course.institution,
         result.course.term, result.course.instructor, result.course.meeting_times,
         result.course.confidence),
    )
    course_id = cur.fetchone()[0]

    # 2. the upload itself
    cur.execute(
        """
        INSERT INTO syllabus_uploads
            (user_id, source, original_filename, mime_type, byte_size, storage_key,
             content_sha256, page_count, status, pipeline_path, model, processing_ms,
             warnings, non_task_weight, grade_weight_total, term_start, term_end,
             infer_dates, extraction_json, course_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'succeeded', %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, content_sha256) DO UPDATE
          SET status = 'succeeded', extraction_json = EXCLUDED.extraction_json
        RETURNING id
        """,
        (user_id, source, original_filename, mime_type, len(raw_bytes), storage_key,
         hashlib.sha256(raw_bytes).hexdigest(), meta.pages,
         meta.pipeline_path.value, meta.model, meta.processing_ms,
         Jsonb(meta.warnings), meta.non_task_weight, meta.grade_weight_total,
         options.term_start, options.term_end, options.infer_dates,
         Jsonb(result.model_dump(mode="json")), course_id),
    )
    upload_id = cur.fetchone()[0]

    # 3. per-page rows (native-text path: char counts; camera: CV metrics)
    for page_number in range(1, meta.pages + 1):
        cur.execute(
            """
            INSERT INTO syllabus_upload_pages (upload_id, page_number, accepted, warnings)
            VALUES (%s, %s, true, '[]'::jsonb)
            ON CONFLICT (upload_id, page_number) DO NOTHING
            """,
            (upload_id, page_number),
        )

    # 4. tasks + subtasks. user_edited rows are never overwritten by a re-extract.
    for task in result.tasks:
        cur.execute(
            """
            INSERT INTO tasks
                (user_id, course_id, upload_id, title, type, due_date, due_time,
                 date_source, needs_review, confidence, grade_pct, priority,
                 priority_score, priority_reason, estimated_hours, completed,
                 source_page, source_quote)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    false, %s, %s)
            RETURNING id
            """,
            (user_id, course_id, upload_id, task.title, task.type.value, task.due_date,
             task.due_time, task.date_source.value, task.needs_review, task.confidence,
             task.grade_pct, task.priority.value, task.priority_score,
             task.priority_reason, task.estimated_hours, task.source_page,
             task.source_quote),
        )
        task_id = cur.fetchone()[0]
        for position, sub in enumerate(task.subtasks):
            cur.execute(
                "INSERT INTO subtasks (task_id, title, days_before, due_date, position) "
                "VALUES (%s, %s, %s, %s, %s)",
                (task_id, sub.title, sub.days_before, sub.due_date, position),
            )

    return upload_id, course_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete existing rows first")
    parser.add_argument("--dsn", default=settings.database_url,
                        help="defaults to $DATABASE_URL from .env")
    args = parser.parse_args()

    options = PipelineOptions(term_start=TERM_START, term_end=TERM_END, today=TODAY,
                              use_gemini=False)
    raw = FIXTURE.read_bytes()
    result = process_pdf(raw, options)

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        if args.reset:
            # CASCADE handles tasks/subtasks/pages via their foreign keys.
            cur.execute("TRUNCATE users CASCADE")
            print("reset: all rows deleted")

        user_id = ensure_user(cur)
        upload_id, course_id = save_result(
            cur, user_id, result,
            source="file",
            raw_bytes=raw,
            mime_type="application/pdf",
            original_filename=FIXTURE.name,
            storage_key=f"s3://syllabi/{FIXTURE.name}",
            options=options,
        )
        conn.commit()

        print(f"user   {user_id}")
        print(f"course {course_id}")
        print(f"upload {upload_id}")
        for table in ("users", "courses", "syllabus_uploads", "syllabus_upload_pages",
                      "tasks", "subtasks"):
            cur.execute(f"SELECT count(*) FROM {table}")
            print(f"  {table:24} {cur.fetchone()[0]} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
