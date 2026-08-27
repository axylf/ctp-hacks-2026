"""Run any syllabus through the pipeline and print a readable report.

This is the test that matters most: the fixture is a regression net, but it
proves nothing about a document the extractor has never seen. Point this at
your own syllabi -- and at things that AREN'T syllabi -- and read the output.

    uv run python ml/scripts/try_syllabus.py path/to/syllabus.pdf
    uv run python ml/scripts/try_syllabus.py photo1.jpg photo2.jpg   # camera path
    uv run python ml/scripts/try_syllabus.py syllabus.pdf --no-infer # raw extraction
    uv run python ml/scripts/try_syllabus.py syllabus.pdf --json     # full contract
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.app.config import settings  # noqa: E402
from ml.app.ingest.pdf import is_pdf  # noqa: E402
from ml.app.pipeline import (  # noqa: E402
    PipelineOptions,
    TooBlurry,
    process_images,
    process_pdf,
)

BAR = "=" * 78


def _date(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="one PDF, or one or more images")
    parser.add_argument("--term-start", type=_date, default=None)
    parser.add_argument("--term-end", type=_date, default=None)
    parser.add_argument("--today", type=_date, default=None)
    parser.add_argument("--no-infer", action="store_true",
                        help="disable date inference -- shows the RAW extraction")
    parser.add_argument("--json", action="store_true", help="dump the full contract")
    args = parser.parse_args()

    options = PipelineOptions(
        term_start=args.term_start,
        term_end=args.term_end,
        today=args.today,
        infer_dates=not args.no_infer,
    )

    paths = [Path(f) for f in args.files]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"not found: {', '.join(str(p) for p in missing)}")
        return 1

    print(BAR)
    print(f"extractor: {'Gemini ' + settings.gemini_model if settings.gemini_enabled else 'offline regex (no GEMINI_API_KEY set)'}")
    print(f"input:     {', '.join(p.name for p in paths)}")
    print(BAR)

    first = paths[0].read_bytes()
    try:
        if len(paths) == 1 and is_pdf(first):
            result = process_pdf(first, options)
        else:
            result = process_images([p.read_bytes() for p in paths], options)
    except TooBlurry as exc:
        print(f"\nREJECTED: {exc}\n  -> retake the photo in better light")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {exc}")
        return 1

    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        return 0

    course, meta = result.course, result.meta
    print(f"\nCOURSE   {course.code} — {course.name}")
    print(f"         {course.institution or '(institution not found)'}")
    print(f"         {course.term or '(term not found)'} · "
          f"{course.instructor or '(instructor not found)'} · "
          f"confidence {course.confidence:.2f}")
    print(f"\nRUN      path={meta.pipeline_path.value} model={meta.model} "
          f"pages={meta.pages} {meta.processing_ms}ms")
    print(f"         grade weight accounted: {meta.grade_weight_total:g}% "
          f"(of which {meta.non_task_weight:g}% has no deadline)")

    if not result.tasks:
        print("\nNO TASKS FOUND.")
        print("  If this really is a syllabus, that's a miss worth investigating.")
        print("  If it isn't, an empty result is the correct answer.")
        return 0

    print(f"\nTASKS ({len(result.tasks)})")
    print(f"  {'PRIORITY':<9} {'DUE':<11} {'SRC':<9} {'WEIGHT':>7}  TITLE")
    print(f"  {'-'*9} {'-'*11} {'-'*9} {'-'*7}  {'-'*30}")
    for task in result.tasks:
        due = task.due_date.isoformat() if task.due_date else "—"
        weight = f"{task.grade_pct:g}%" if task.grade_pct is not None else "—"
        flag = " ⚑" if task.needs_review else ""
        print(f"  {task.priority.value:<9} {due:<11} {task.date_source.value:<9} "
              f"{weight:>7}  {task.title}{flag}")

    flagged = [t for t in result.tasks if t.needs_review]
    if flagged:
        print(f"\n  ⚑ {len(flagged)} flagged for review — the student should confirm these")

    print("\nPROVENANCE (what each task was read from)")
    for task in result.tasks[:6]:
        quote = task.source_quote or "(none)"
        print(f"  p{task.source_page or '?'}  {task.title[:28]:<28} \"{quote[:44]}\"")

    if result.workload_analysis.windows:
        print(f"\nCRUNCH PERIODS ({len(result.workload_analysis.windows)})")
        for window in result.workload_analysis.windows:
            print(f"  [{window.severity.value.upper():8}] {window.start} → {window.end} "
                  f"load {window.load_score} — {window.label}")
    else:
        print("\nCRUNCH PERIODS  none detected")

    if result.recommendations:
        print(f"\nRECOMMENDATIONS ({len(result.recommendations)})")
        for rec in result.recommendations:
            print(f"  [{rec.type}] {rec.message}")
            for sub in rec.suggested_subtasks:
                print(f"       T-{sub.days_before}d  {sub.title}")

    if meta.warnings:
        print(f"\nWARNINGS ({len(meta.warnings)})")
        for warning in meta.warnings:
            print(f"  · {warning}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
