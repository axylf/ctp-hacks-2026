"""Resolve whatever the syllabus printed into a real calendar date.

Anchored on the term, always. A bare "3/10" in a Spring 2026 course is
2026-03-10 — never 2025, and never "March 10th of whatever year it is today".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from dateutil import parser as duparser

_TERM_RE = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(20\d{2})\b", re.I)

# Rough US academic calendar, used only when the caller gives us no term dates.
_TERM_DEFAULTS = {
    "spring": ((1, 26), (5, 20)),
    "summer": ((6, 1), (8, 15)),
    "fall": ((8, 28), (12, 18)),
    "autumn": ((8, 28), (12, 18)),
    "winter": ((1, 2), (1, 25)),
}

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}


@dataclass(frozen=True)
class TermCalendar:
    start: date
    end: date

    @property
    def n_weeks(self) -> int:
        return max(1, ((self.end - self.start).days // 7) + 1)

    def week_start(self, week_number: int) -> date:
        """Monday of week N (1-indexed), clamped inside the term."""
        week_number = max(1, week_number)
        monday = self.start - timedelta(days=self.start.weekday())
        target = monday + timedelta(weeks=week_number - 1)
        return min(max(target, self.start), self.end)

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end


def term_calendar_from_label(label: str | None) -> TermCalendar | None:
    """'Spring 2026' -> a default calendar. Rough by design; the caller should
    pass real dates when it has them."""
    if not label:
        return None
    match = _TERM_RE.search(label)
    if not match:
        return None
    season, year = match.group(1).lower(), int(match.group(2))
    (sm, sd), (em, ed) = _TERM_DEFAULTS[season]
    return TermCalendar(start=date(year, sm, sd), end=date(year, em, ed))


def _apply_weekday(anchor: date, text: str) -> date:
    """'Friday of week 8' -> that Friday, given the Monday of week 8."""
    for name, index in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text, re.I):
            return anchor + timedelta(days=index - anchor.weekday())
    return anchor


def parse_due(raw: str, term: TermCalendar | None) -> date | None:
    """Best-effort resolution. Returns None rather than guessing — an unparsed
    date becomes needs_review, which is honest; a wrong date is not."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    if re.search(r"\b(tba|tbd|announced|posted|blackboard|canvas|lms)\b", text, re.I):
        return None

    week = re.search(r"\bweek\s+(\d{1,2})\b", text, re.I)
    if week and term:
        return _apply_weekday(term.week_start(int(week.group(1))), text)
    if week:
        return None

    # Bare M/D or "March 10" with no year: resolve inside the term.
    has_year = re.search(r"\b(19|20)\d{2}\b", text) is not None
    candidate_years = [term.start.year, term.end.year] if term else []

    if not has_year and candidate_years:
        for year in dict.fromkeys(candidate_years):
            try:
                parsed = duparser.parse(text, default=_default_for(year), fuzzy=True).date()
            except (ValueError, OverflowError):
                continue
            if term and term.contains(parsed):
                return parsed
        # Parsed fine but landed outside the term — keep the first reading
        # rather than discarding a date the syllabus actually printed.
        try:
            return duparser.parse(
                text, default=_default_for(candidate_years[0]), fuzzy=True
            ).date()
        except (ValueError, OverflowError):
            return None

    try:
        return duparser.parse(text, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def _default_for(year: int):
    from datetime import datetime

    return datetime(year, 1, 1)
