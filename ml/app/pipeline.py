"""Stages 1-7, wired together.

The whole point of the layering: only `_extract_*` can fail non-deterministically,
and when it does the pipeline degrades to the regex extractor instead of
returning nothing.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date

from .analyze import overlap, recommend
from .config import ESTIMATED_HOURS, settings
from .extract import fallback
from .extract.gemini import GeminiUnavailable, extract_from_images, extract_from_text
from .ingest import image as cv_ingest
from .ingest import pdf as pdf_ingest
from .ingest.router import decide_path, decide_path_for_images
from .normalize import dedupe as dedupe_mod
from .normalize import infer, priority
from .normalize.dates import TermCalendar, parse_due, term_calendar_from_label
from .schemas import (
    Course,
    DateSource,
    ExtractionResult,
    Meta,
    PipelinePath,
    RawExtraction,
    RawTask,
    Task,
    TaskType,
)

log = logging.getLogger(__name__)


class TooBlurry(ValueError):
    """Raised before any API call, so a bad photo costs nothing."""

    def __init__(self, score: float):
        self.score = score
        super().__init__(
            f"image too blurry to read (focus score {score:.0f}, "
            f"need {settings.blur_reject_below:.0f})"
        )


@dataclass
class PipelineOptions:
    term_start: date | None = None
    term_end: date | None = None
    infer_dates: bool = True
    today: date | None = None
    use_gemini: bool | None = None   # None = auto (use it when a key is present)

    def resolved_today(self) -> date:
        return self.today or date.today()

    def resolved_use_gemini(self) -> bool:
        return settings.gemini_enabled if self.use_gemini is None else self.use_gemini


# ---------------------------------------------------------------------------
# raw -> contract
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"


def _expand(raw: RawTask, course_code: str, index: int) -> list[Task]:
    """'~4 programming assignments (40%)' becomes four tasks at 10% each, so
    they can be scheduled and checked off individually."""
    count = max(1, min(raw.count, 20))
    per_item_pct = (raw.grade_pct / count) if raw.grade_pct is not None else None
    base_title = re.sub(r"s$", "", raw.title.strip()) if count > 1 else raw.title.strip()
    prefix = _slug(course_code)

    out: list[Task] = []
    for n in range(1, count + 1):
        title = f"{base_title} {n}" if count > 1 else base_title
        out.append(
            Task(
                id=f"{prefix}-{_slug(title)}-{index}{n if count > 1 else ''}",
                course_code=course_code,
                title=title,
                type=raw.type,
                grade_pct=per_item_pct,
                confidence=raw.confidence,
                source_page=raw.source_page,
                source_quote=raw.source_quote,
                estimated_hours=ESTIMATED_HOURS.get(raw.type.value),
            )
        )
    return out


def normalize(
    raw: RawExtraction, options: PipelineOptions
) -> tuple[Course, list[Task], list[str], TermCalendar | None]:
    warnings: list[str] = []

    course = Course(
        code=raw.course.code or "UNKNOWN",
        name=raw.course.name or "Untitled Course",
        institution=raw.course.institution or None,
        term=raw.course.term or None,
        instructor=raw.course.instructor or None,
        meeting_times=raw.course.meeting_times,
        confidence=max(0.0, min(1.0, raw.course.confidence)),
    )

    if options.term_start and options.term_end:
        term = TermCalendar(options.term_start, options.term_end)
    else:
        term = term_calendar_from_label(course.term)
        if term:
            warnings.append(
                f"term dates not supplied; assuming {term.start} to {term.end} "
                f"from '{course.term}'"
            )

    tasks: list[Task] = []
    for index, raw_task in enumerate(raw.tasks):
        expanded = _expand(raw_task, course.code, index)
        for task in expanded:
            resolved = parse_due(raw_task.due_raw, term)
            if resolved is not None:
                task.due_date = resolved
                task.date_source = DateSource.EXPLICIT
            elif raw_task.due_raw.strip():
                # A date was printed but we couldn't resolve it — say so
                # rather than silently dropping it.
                task.needs_review = True
                warnings.append(f"could not resolve due date {raw_task.due_raw!r} for {task.title}")
            tasks.append(task)

    tasks = dedupe_mod.dedupe(tasks)

    undated = [t for t in tasks if t.due_date is None]
    if undated and options.infer_dates and term:
        infer.infer_schedule(tasks, term)
        warnings.append(
            f"no explicit due dates for {len(undated)} task(s); "
            "dates inferred from the term calendar and flagged for review"
        )
    elif undated:
        for task in undated:
            task.date_source = DateSource.UNKNOWN
            task.needs_review = True
        warnings.append(f"{len(undated)} task(s) have no due date")

    for task in tasks:
        if task.confidence < 0.6:
            task.needs_review = True

    return course, tasks, warnings, term


def finish(
    course: Course,
    tasks: list[Task],
    path: PipelinePath,
    model: str,
    warnings: list[str],
    options: PipelineOptions,
    pages: int,
    non_task_weight: float = 0.0,
) -> ExtractionResult:
    """Stages 5b-7: score, analyze, advise."""
    today = options.resolved_today()

    priority.score_all(tasks, today, overlap.week_loads(tasks))
    analysis = overlap.analyze(tasks)
    # Rescore once more now that window loads are known, so a task sitting in a
    # crunch week outranks an identical one in a quiet week.
    priority.score_all(tasks, today, overlap.week_loads(tasks))

    recommendations = recommend.recommend(
        tasks, analysis, today, use_gemini=options.resolved_use_gemini()
    )
    tasks.sort(key=lambda t: (-t.priority_score, t.due_date or date.max))

    return ExtractionResult(
        course=course,
        tasks=tasks,
        workload_analysis=analysis,
        recommendations=recommendations,
        meta=Meta(
            pipeline_path=path,
            model=model,
            warnings=warnings,
            pages=pages,
            non_task_weight=non_task_weight,
            grade_weight_total=round(
                sum(t.grade_pct or 0.0 for t in tasks) + non_task_weight, 2
            ),
        ),
    )


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def process_pdf(data: bytes, options: PipelineOptions | None = None) -> ExtractionResult:
    options = options or PipelineOptions()
    started = time.perf_counter()

    doc = pdf_ingest.extract_pdf(data)
    route = decide_path(doc, settings.text_density_threshold)
    warnings = [f"routing: {route.reason}"]

    if route.path is PipelinePath.NATIVE_TEXT:
        raw, path, model = _extract_text(doc.text, [p.text for p in doc.pages])
    else:
        # No usable text layer: rasterize and look at the pixels instead.
        images = pdf_ingest.render_pages(data)
        raw, path, model = _extract_images(images, fallback_text=doc.text)
        if route.path is PipelinePath.HYBRID and path is not PipelinePath.FALLBACK:
            path = PipelinePath.HYBRID

    result = _assemble(raw, path, model, warnings, options, doc.n_pages)
    result.meta.processing_ms = int((time.perf_counter() - started) * 1000)
    return result


def process_images(
    images: list[bytes], options: PipelineOptions | None = None
) -> ExtractionResult:
    """Camera path. Preprocess every frame, reject unreadable ones early."""
    options = options or PipelineOptions()
    started = time.perf_counter()

    decide_path_for_images(len(images))
    processed: list[bytes] = []
    warnings: list[str] = []
    best_blur = 0.0

    for index, frame in enumerate(images, start=1):
        result = cv_ingest.preprocess(frame)
        best_blur = max(best_blur, result.blur_score)
        if result.too_blurry:
            warnings.append(f"page {index}: skipped, focus score {result.blur_score:.0f}")
            continue
        if abs(result.skew_corrected_deg) >= 0.5:
            warnings.append(f"page {index}: corrected {result.skew_corrected_deg:.1f}deg skew")
        if not result.document_found:
            warnings.append(f"page {index}: no page border detected")
        processed.append(result.to_png())

    if not processed:
        raise TooBlurry(best_blur)

    raw, path, model = _extract_images(processed)
    result = _assemble(raw, path, model, warnings, options, len(processed))
    result.meta.processing_ms = int((time.perf_counter() - started) * 1000)
    return result


def _assemble(
    raw: RawExtraction,
    path: PipelinePath,
    model: str,
    warnings: list[str],
    options: PipelineOptions,
    pages: int,
) -> ExtractionResult:
    course, tasks, more_warnings, _ = normalize(raw, options)
    return finish(
        course, tasks, path, model, warnings + more_warnings, options, pages,
        non_task_weight=raw.non_task_weight,
    )


def _extract_text(text: str, page_texts: list[str]) -> tuple[RawExtraction, PipelinePath, str]:
    if settings.gemini_enabled:
        try:
            result = extract_from_text(text)
            if result.extraction.tasks:
                return result.extraction, PipelinePath.NATIVE_TEXT, result.model
            log.warning("Gemini returned no tasks; falling back to the regex extractor")
        except (GeminiUnavailable, ValueError) as exc:
            log.warning("Gemini text extraction unavailable (%s); using fallback", exc)
    return fallback.extract(text, page_texts), PipelinePath.FALLBACK, "offline-regex"


def _extract_images(
    images: list[bytes], fallback_text: str = ""
) -> tuple[RawExtraction, PipelinePath, str]:
    if settings.gemini_enabled:
        try:
            result = extract_from_images(images)
            return result.extraction, PipelinePath.VISION, result.model
        except (GeminiUnavailable, ValueError) as exc:
            log.warning("Gemini vision extraction unavailable (%s); using fallback", exc)
    # No key and no OCR: the regex extractor can only work on whatever text we
    # already had. Honest empty result beats a fabricated one.
    return fallback.extract(fallback_text), PipelinePath.FALLBACK, "offline-regex"


def analyze_tasks(tasks: list[Task], options: PipelineOptions | None = None):
    """Cross-course entry point: the backend owns the union of tasks, so this
    takes already-extracted tasks from many syllabi and finds the collisions."""
    options = options or PipelineOptions()
    today = options.resolved_today()
    priority.score_all(tasks, today, overlap.week_loads(tasks))
    analysis = overlap.analyze(tasks)
    priority.score_all(tasks, today, overlap.week_loads(tasks))
    recommendations = recommend.recommend(
        tasks, analysis, today, use_gemini=options.resolved_use_gemini()
    )
    tasks.sort(key=lambda t: (-t.priority_score, t.due_date or date.max))
    return tasks, analysis, recommendations
