"""THE integration contract.

Frozen deliberately: the Flask backend and the frontend build against these
shapes while the pipeline is still being written. Changing a field here is a
breaking change for two other people, so don't do it casually — the golden
snapshot test in tests/test_intro_to_networks.py will fail loudly if you do.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class TaskType(str, Enum):
    ASSIGNMENT = "assignment"
    QUIZ = "quiz"
    EXAM = "exam"
    MIDTERM = "midterm"
    FINAL = "final"
    PROJECT = "project"
    PAPER = "paper"
    PRESENTATION = "presentation"
    READING = "reading"
    OTHER = "other"


class DateSource(str, Enum):
    EXPLICIT = "explicit"   # printed in the syllabus
    INFERRED = "inferred"   # placed by us on the term calendar
    UNKNOWN = "unknown"     # no date, and inference was off


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Severity(str, Enum):
    CRITICAL = "critical"
    HEAVY = "heavy"
    MODERATE = "moderate"


class PipelinePath(str, Enum):
    NATIVE_TEXT = "native_text"
    VISION = "vision"
    HYBRID = "hybrid"
    FALLBACK = "fallback"


# ---------------------------------------------------------------------------
# Raw extraction shapes — what the model (or the regex baseline) returns,
# before any normalization. Kept flat and permissive so Gemini's structured
# output has the smallest possible schema to satisfy.
# ---------------------------------------------------------------------------

class RawTask(BaseModel):
    title: str
    type: TaskType = TaskType.OTHER
    # Free text exactly as printed: "Week 5", "3/10", "TBA", or empty.
    # NEVER a guess — see prompts.SYSTEM_PROMPT.
    due_raw: str = ""
    grade_pct: Optional[float] = None
    count: int = 1              # "~4 programming assignments" -> count=4
    confidence: float = 0.5
    source_page: Optional[int] = None
    source_quote: str = ""


class RawCourse(BaseModel):
    code: str = ""
    name: str = ""
    institution: str = ""
    term: str = ""
    instructor: str = ""
    meeting_times: Optional[str] = None
    confidence: float = 0.5


class RawExtraction(BaseModel):
    course: RawCourse = Field(default_factory=RawCourse)
    tasks: list[RawTask] = Field(default_factory=list)
    # Grade weight belonging to non-schedulable components (participation,
    # attendance). Deliberately NOT tasks — you cannot "complete"
    # participation — but tracked so callers can verify the grading table
    # was parsed whole: sum(task weights) + non_task_weight should hit 100.
    non_task_weight: float = 0.0


# ---------------------------------------------------------------------------
# Normalized output — the contract teammates consume
# ---------------------------------------------------------------------------

class Subtask(BaseModel):
    title: str
    days_before: int = Field(ge=1)
    due_date: Optional[date] = None
    completed: bool = False


class Course(BaseModel):
    code: str
    name: str
    institution: Optional[str] = None
    term: Optional[str] = None
    instructor: Optional[str] = None
    meeting_times: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class Task(BaseModel):
    id: str
    course_code: str
    title: str
    type: TaskType
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    date_source: DateSource = DateSource.UNKNOWN
    grade_pct: Optional[float] = None
    priority: Priority = Priority.MEDIUM
    priority_score: float = 0.0
    priority_reason: str = ""
    estimated_hours: Optional[int] = None
    completed: bool = False
    needs_review: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    source_page: Optional[int] = None
    source_quote: str = ""
    subtasks: list[Subtask] = Field(default_factory=list)

    @field_validator("grade_pct")
    @classmethod
    def _sane_pct(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return max(0.0, min(100.0, float(v)))


class WorkloadWindow(BaseModel):
    start: date
    end: date
    load_score: float
    severity: Severity
    task_ids: list[str]
    label: str
    kind: Literal["iso_week", "rolling_7d"] = "iso_week"


class WorkloadAnalysis(BaseModel):
    windows: list[WorkloadWindow] = Field(default_factory=list)


class Recommendation(BaseModel):
    type: Literal[
        "start_early", "break_into_subtasks", "front_load_study", "overdue"
    ]
    target_task_id: str
    message: str
    window: Optional[str] = None
    suggested_subtasks: list[Subtask] = Field(default_factory=list)


class Meta(BaseModel):
    pipeline_path: PipelinePath
    model: str
    warnings: list[str] = Field(default_factory=list)
    processing_ms: int = 0
    pages: int = 0
    # see RawExtraction.non_task_weight
    non_task_weight: float = 0.0
    grade_weight_total: float = 0.0


class ExtractionResult(BaseModel):
    course: Course
    tasks: list[Task] = Field(default_factory=list)
    workload_analysis: WorkloadAnalysis = Field(default_factory=WorkloadAnalysis)
    recommendations: list[Recommendation] = Field(default_factory=list)
    meta: Meta


class PipelineError(BaseModel):
    """Returned instead of a result when input is unusable (e.g. too blurry)."""
    error: str
    detail: str = ""
    retake: bool = False
