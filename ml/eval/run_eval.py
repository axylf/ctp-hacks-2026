"""Measurement, not a pass/fail test.

Run this by hand while tuning prompts. It scores an extractor against
hand-labeled ground truth and, when a key is present, reports the delta between
Gemini and the regex baseline. This is what turns prompt iteration from vibes
into evidence.

    uv run python ml/eval/run_eval.py              # baseline only
    uv run python ml/eval/run_eval.py --gemini     # both, needs GEMINI_API_KEY
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rapidfuzz import fuzz  # noqa: E402

from ml.app.config import settings  # noqa: E402
from ml.app.extract import fallback  # noqa: E402
from ml.app.extract.gemini import extract_from_text  # noqa: E402
from ml.app.ingest.pdf import extract_pdf  # noqa: E402
from ml.app.schemas import RawExtraction  # noqa: E402

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT.parent / "tests" / "fixtures"
TITLE_MATCH_THRESHOLD = 70


@dataclass
class Score:
    name: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    type_correct: int = 0
    weight_correct: int = 0
    date_correct: int = 0
    hallucinated_dates: int = 0
    course_fields_correct: int = 0
    course_fields_total: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _match(expected: dict, predicted_tasks: list) -> object | None:
    best, best_score = None, 0
    for task in predicted_tasks:
        if task.type.value != expected["type"]:
            continue
        score = fuzz.token_set_ratio(expected["title"].lower(), task.title.lower())
        if score > best_score:
            best, best_score = task, score
    return best if best_score >= TITLE_MATCH_THRESHOLD else None


def score(label: dict, extraction: RawExtraction, name: str) -> Score:
    result = Score(name=name)
    remaining = list(extraction.tasks)

    for expected in label["tasks"]:
        found = _match(expected, remaining)
        if found is None:
            result.false_negatives += 1
            continue
        remaining.remove(found)
        result.true_positives += 1
        if found.type.value == expected["type"]:
            result.type_correct += 1
        if expected.get("grade_pct") is not None and found.grade_pct is not None:
            if abs(found.grade_pct - expected["grade_pct"]) < 0.51:
                result.weight_correct += 1
        # The key metric for this fixture: an empty expected date must stay empty.
        if (found.due_raw or "").strip() == (expected.get("due_raw") or "").strip():
            result.date_correct += 1
        elif not (expected.get("due_raw") or "").strip() and (found.due_raw or "").strip():
            result.hallucinated_dates += 1

    result.false_positives = len(remaining)

    for field, want in label["course"].items():
        result.course_fields_total += 1
        got = getattr(extraction.course, field, "") or ""
        if fuzz.partial_ratio(str(want).lower(), str(got).lower()) >= 85:
            result.course_fields_correct += 1

    return result


def report(scores: list[Score], label: dict) -> None:
    width = max([len(s.name) for s in scores] + [12]) + 2
    header = (f"{'extractor':<{width}}{'P':>6}{'R':>6}{'F1':>6}"
              f"{'type':>8}{'weight':>8}{'date':>8}{'halluc':>8}{'course':>8}")
    print(header)
    print("-" * len(header))
    total = len(label["tasks"])
    for s in scores:
        print(
            f"{s.name:<{width}}{s.precision:>6.2f}{s.recall:>6.2f}{s.f1:>6.2f}"
            f"{f'{s.type_correct}/{total}':>8}{f'{s.weight_correct}/{total}':>8}"
            f"{f'{s.date_correct}/{total}':>8}{s.hallucinated_dates:>8}"
            f"{f'{s.course_fields_correct}/{s.course_fields_total}':>8}"
        )
    print()
    print("halluc = dates invented for items the syllabus gives no date for.")
    print("Lower is better and it is never acceptable; a nonzero value here means")
    print("the extractor is confidently wrong, which is worse than being empty.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini", action="store_true", help="also score the live model")
    args = parser.parse_args()

    scores: list[Score] = []
    for label_path in sorted((ROOT / "labels").glob("*.json")):
        label = json.loads(label_path.read_text())
        pdf = FIXTURES / label["fixture"]
        if not pdf.exists():
            print(f"skipping {label_path.name}: missing {pdf}")
            continue

        doc = extract_pdf(pdf.read_bytes())
        print(f"\n=== {label_path.stem} ({doc.n_pages} pages, {doc.total_chars} chars) ===\n")

        scores.append(score(label, fallback.extract(doc.text, [p.text for p in doc.pages]),
                            "offline-regex"))

        if args.gemini:
            if not settings.gemini_enabled:
                print("--gemini requested but GEMINI_API_KEY is not set; skipping.\n")
            else:
                try:
                    result = extract_from_text(doc.text)
                    scores.append(score(label, result.extraction, result.model))
                except Exception as exc:  # noqa: BLE001
                    print(f"Gemini run failed: {exc}\n")

        report(scores, label)
        scores = []
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
