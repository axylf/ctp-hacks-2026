"""Offline extractor — regex and heuristics, no API key, no network.

Three jobs at once:
  1. the CI extractor (free, deterministic, no flake)
  2. the degraded-mode path when Gemini is down or rate-limited
  3. the BASELINE the eval harness measures Gemini against — if the model
     can't beat regex on our labeled set, that's worth knowing
"""
from __future__ import annotations

import re

from ..schemas import RawCourse, RawExtraction, RawTask, TaskType

# --- type classification ---------------------------------------------------
# Order matters: "final exam" must hit FINAL before EXAM, and "midterm exam"
# must hit MIDTERM before EXAM.
_TYPE_PATTERNS: list[tuple[TaskType, str]] = [
    (TaskType.FINAL, r"\bfinals?\b|\bfinal\s+(?:exam|project|paper|presentation)\b"),
    (TaskType.MIDTERM, r"\bmid-?terms?\b"),
    (TaskType.QUIZ, r"\bquiz(?:zes)?\b"),
    (TaskType.EXAM, r"\bexams?\b|\btests?\b"),
    (TaskType.PAPER, r"\bpapers?\b|\bessays?\b|\bwrite-?ups?\b|\breports?\b"),
    (TaskType.PRESENTATION, r"\bpresentations?\b|\btalks?\b|\bdemos?\b"),
    (TaskType.PROJECT, r"\bprojects?\b"),
    (TaskType.READING, r"\breadings?\b"),
    (TaskType.ASSIGNMENT,
     r"\bassignments?\b|\bhomework\b|\bhw\s*\d*\b|\bproblem\s+sets?\b|\bpsets?\b|\blabs?\b"),
]

_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
DATE_RE = re.compile(
    rf"(?:(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?"
    rf"|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?"
    rf"|\bweek\s+\d{{1,2}}\b)",
    re.I,
)

# "40% - ~4 programming assignments"  /  "Final Exam ..... 30%"
_PCT_FIRST = re.compile(r"^\s*[-*•]?\s*(\d{1,3}(?:\.\d+)?)\s*%\s*[-–—:\.]*\s*(.+?)\s*:?\s*$")
_PCT_LAST = re.compile(r"^\s*[-*•]?\s*(.+?)\s*[-–—:\.\s]+(\d{1,3}(?:\.\d+)?)\s*%\s*$")
_COUNT_RE = re.compile(r"(?:^|\s)~?(\d{1,2})\s+(?=[a-z])", re.I)

_COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,5})\s*[- ]?\s*(\d{3}[A-Z]?(?:\s*/\s*\d{3}[A-Z]?)*)\b")
_TERM_RE = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(20\d{2})\b", re.I)
_INSTRUCTOR_RE = re.compile(
    r"^\s*(?:instructor|professor|prof|taught\s+by)\s*[:\-]\s*(.+?)\s*$", re.I | re.M
)
_INSTITUTION_RE = re.compile(r"^.*\b(college|university|institute|school)\b.*$", re.I | re.M)

# Lines that look like grading rows but aren't graded work.
_NOT_A_TASK = re.compile(r"\bparticipation\b|\battendance\b|\bengagement\b", re.I)
_PLAN_HEADING = re.compile(r"\b(?:tentative|tenatative)\s+plan\b", re.I)
_PLAN_ROW = re.compile(
    r"^\s*(\d{1,2}(?:\s*/\s*\d{1,2})*)\s+.+?\s+"
    r"((?:lab|exam|quiz|project|paper|presentation|assignment)\s*\d*\b.*?)\s*$",
    re.I,
)


def classify(label: str) -> TaskType:
    for task_type, pattern in _TYPE_PATTERNS:
        if re.search(pattern, label, re.I):
            return task_type
    return TaskType.OTHER


def _titleize(label: str) -> str:
    label = re.sub(r"^\s*~?\d+\s+", "", label.strip())      # drop a leading count
    label = re.sub(r"\s*[:\-–—]\s*$", "", label)            # drop trailing punctuation
    label = re.sub(r"\s+", " ", label)
    words = label.split()
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


def _page_of(text: str, index: int, page_breaks: list[int]) -> int:
    return sum(1 for b in page_breaks if b <= index) + 1


def extract_course(text: str) -> RawCourse:
    head = "\n".join(text.splitlines()[:8])

    code, name = "", ""
    titled = re.search(r"^\s*([A-Z]{2,5}\s*\d{3}[A-Z]?(?:\s*/\s*\d{3}[A-Z]?)*)\s*:\s*(.+?)\s*$",
                       head, re.M)
    if titled:
        code = re.sub(r"\s*/\s*", "/", titled.group(1).strip())
        name = titled.group(2).strip()
    else:
        found = _COURSE_CODE_RE.search(head)
        if found:
            code = f"{found.group(1)} {re.sub(r'\\s*/\\s*', '/', found.group(2))}"
        first = next((line.strip() for line in head.splitlines() if line.strip()), "")
        name = re.sub(r"^\s*[A-Z]{2,5}\s*\d{3}.*?:\s*", "", first)

    term_match = _TERM_RE.search(head) or _TERM_RE.search(text)
    term = f"{term_match.group(1).capitalize()} {term_match.group(2)}" if term_match else ""

    institution_match = _INSTITUTION_RE.search(head)
    institution = institution_match.group(0).strip() if institution_match else ""

    instructor_match = _INSTRUCTOR_RE.search(text)
    instructor = instructor_match.group(1).strip() if instructor_match else ""
    if not instructor:
        prof = re.search(r"\bProf(?:essor)?\.?\s+([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,2})", text)
        instructor = prof.group(1).strip() if prof else ""

    # Confidence reflects how much of the header we actually pinned down.
    filled = sum(bool(v) for v in (code, name, term, institution, instructor))
    return RawCourse(
        code=code or "UNKNOWN",
        name=name or "Untitled Course",
        institution=institution,
        term=term,
        instructor=instructor,
        confidence=round(0.4 + 0.12 * filled, 2),
    )


def _graded_rows(text: str, page_breaks: list[int]) -> tuple[list[RawTask], float]:
    """Returns (tasks, weight belonging to non-schedulable components)."""
    tasks: list[RawTask] = []
    non_task_weight = 0.0
    offset = 0
    for line in text.splitlines():
        index, offset = offset, offset + len(line) + 1
        stripped = line.strip()
        if not stripped or "%" not in stripped:
            continue

        match = _PCT_FIRST.match(stripped)
        if match:
            pct, label = float(match.group(1)), match.group(2)
        else:
            match = _PCT_LAST.match(stripped)
            if not match:
                continue
            label, pct = match.group(1), float(match.group(2))

        if pct <= 0 or pct > 100 or len(label) > 90:
            continue
        if _NOT_A_TASK.search(label):
            # Real grade weight, but nothing to put a deadline on.
            non_task_weight += pct
            continue

        count_match = _COUNT_RE.search(" " + label)
        count = int(count_match.group(1)) if count_match else 1
        count = count if 1 <= count <= 20 else 1

        date_match = DATE_RE.search(label)
        tasks.append(
            RawTask(
                title=_titleize(label),
                type=classify(label),
                due_raw=date_match.group(0) if date_match else "",
                grade_pct=pct,
                count=count,
                confidence=0.75,
                source_page=_page_of(text, index, page_breaks),
                source_quote=stripped[:120],
            )
        )
    return tasks, non_task_weight


def _dated_rows(text: str, page_breaks: list[int], seen: list[str]) -> list[RawTask]:
    """Lines that pair a task keyword with a date — a schedule table, typically.
    Skipped if we already captured that item from the grading breakdown."""
    tasks: list[RawTask] = []
    seen_lower = {s.lower() for s in seen}
    offset = 0
    in_plan = False
    for line in text.splitlines():
        index, offset = offset, offset + len(line) + 1
        stripped = line.strip()
        if _PLAN_HEADING.search(stripped):
            in_plan = True
            continue
        if in_plan and re.match(r"^\d+\.\s+(?:grading|grade|attendance|academic)\b", stripped, re.I):
            in_plan = False
        if in_plan:
            continue
        if not stripped or "%" in stripped or len(stripped) > 150:
            continue
        date_match = DATE_RE.search(stripped)
        if not date_match:
            continue
        task_type = classify(stripped)
        if task_type is TaskType.OTHER:
            continue

        label = _titleize(DATE_RE.sub("", stripped).strip(" .,–—-:"))
        if not label or label.lower() in seen_lower:
            continue
        tasks.append(
            RawTask(
                title=label[:80],
                type=task_type,
                due_raw=date_match.group(0),
                count=1,
                confidence=0.6,
                source_page=_page_of(text, index, page_breaks),
                source_quote=stripped[:120],
            )
        )
    return tasks


def _tentative_plan_rows(text: str, page_breaks: list[int]) -> list[RawTask]:
    """Extract rows such as ``3/4/5 ... Lab 2`` from a tentative-plan table.

    These are schedule weeks, not calendar dates. Keeping the week label avoids
    inventing dates from an academic-calendar approximation.
    """
    tasks: list[RawTask] = []
    in_plan = False
    offset = 0
    for line in text.splitlines():
        index, offset = offset, offset + len(line) + 1
        stripped = line.strip()
        if _PLAN_HEADING.search(stripped):
            in_plan = True
            continue
        if not in_plan:
            continue
        if re.match(r"^\d+\.\s+(?:grading|grade|attendance|academic)\b", stripped, re.I):
            break
        match = _PLAN_ROW.match(stripped)
        if not match:
            continue
        week_label = re.sub(r"\s*/\s*", "/", match.group(1))
        label = match.group(2).strip()
        tasks.append(
            RawTask(
                title=_titleize(label),
                type=classify(label),
                week_label=week_label,
                confidence=0.9,
                source_page=_page_of(text, index, page_breaks),
                source_quote=stripped[:120],
            )
        )
    return tasks


def extract(text: str, page_texts: list[str] | None = None) -> RawExtraction:
    """Regex/heuristic extraction over already-normalized syllabus text."""
    page_breaks: list[int] = []
    if page_texts:
        running = 0
        for page in page_texts[:-1]:
            running += len(page) + 1
            page_breaks.append(running)

    graded, non_task_weight = _graded_rows(text, page_breaks)
    dated = _dated_rows(text, page_breaks, [t.title for t in graded])
    planned = _tentative_plan_rows(text, page_breaks)
    return RawExtraction(
        course=extract_course(text),
        tasks=graded + dated + planned,
        non_task_weight=non_task_weight,
    )
