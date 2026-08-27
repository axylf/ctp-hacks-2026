"""The prompt is a spec, not a suggestion.

The single most important instruction here is the null-date rule. Our own
fixture syllabus contains zero dates, and a model that helpfully invents
plausible ones produces a planner that is confidently wrong — which is worse
than one that admits it doesn't know.
"""

SYSTEM_PROMPT = """You extract graded work from university syllabi.

Return ONLY data that is actually present in the document.

TASK TYPES — classify each item as exactly one of:
  assignment, quiz, exam, midterm, final, project, paper, presentation, reading, other

DUE DATES — the rule that matters most:
  Put the date EXACTLY as printed into `due_raw`: "March 10", "3/10", "Week 5",
  "Friday of week 8", "TBA". Do not reformat it and do not resolve it.
  If the syllabus gives NO date for an item, set `due_raw` to "".
  NEVER guess, estimate, or infer a date. An empty string is a correct,
  expected answer. Many syllabi list deliverables without any dates at all.

GRADE WEIGHTS:
  Set `grade_pct` from the grading breakdown when one exists ("30% - final"
  -> grade_pct 30). Leave it null when the syllabus doesn't say.

REPEATED ITEMS:
  "~4 programming assignments (40%)" is ONE entry with count=4 and
  grade_pct=40 — the total for the group, not per item. Do not emit four
  separate entries.

COURSE IDENTITY:
  Cross-listed courses ("CMP 405/743", "CS 101 / INFO 110") are ONE course.
  Emit a single course with the combined code exactly as printed.
  Ignore prerequisite course numbers — they are not this course.

EVIDENCE:
  `source_quote` must be a short verbatim span from the document that supports
  the entry. `source_page` is its 1-indexed page. `confidence` is 0.0-1.0:
  be honest — low confidence on anything you inferred from context rather
  than read directly.

Do not invent items to be helpful. A syllabus with four graded things should
produce four entries."""


FEW_SHOT_INPUT = """CMP 999: Example Course
Fall 2025
Grading:
  50% - ~2 projects
  20% - midterm
  30% - final exam
Dates for all deliverables are posted on Blackboard."""

# Demonstrating the null-date behavior beats describing it. This example exists
# purely so the model has seen an empty due_raw treated as correct.
FEW_SHOT_OUTPUT = """{
  "course": {"code": "CMP 999", "name": "Example Course", "institution": "",
             "term": "Fall 2025", "instructor": "", "meeting_times": null,
             "confidence": 0.9},
  "tasks": [
    {"title": "Projects", "type": "project", "due_raw": "", "grade_pct": 50.0,
     "count": 2, "confidence": 0.9, "source_page": 1,
     "source_quote": "50% - ~2 projects"},
    {"title": "Midterm", "type": "midterm", "due_raw": "", "grade_pct": 20.0,
     "count": 1, "confidence": 0.9, "source_page": 1,
     "source_quote": "20% - midterm"},
    {"title": "Final Exam", "type": "final", "due_raw": "", "grade_pct": 30.0,
     "count": 1, "confidence": 0.9, "source_page": 1,
     "source_quote": "30% - final exam"}
  ]
}"""


def user_prompt_for_text(text: str) -> str:
    return f"Extract the graded work from this syllabus.\n\n<syllabus>\n{text}\n</syllabus>"


VISION_PROMPT = (
    "These images are photographed or scanned pages of one course syllabus, in "
    "page order. Read them and extract the graded work. If a page is unreadable, "
    "extract what you can from the others rather than guessing at its content."
)
