"""The seam.

The real Flask backend owns persistence. This module defines the interface it
should implement and ships an in-memory version so the ML service runs and
tests end-to-end today. Swapping in Postgres means implementing `Repository`
and passing it to `create_app(repository=...)` — nothing else changes.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .schemas import Course, ExtractionResult, Task


@runtime_checkable
class Repository(Protocol):
    def save_result(self, result: ExtractionResult) -> None: ...
    def all_tasks(self) -> list[Task]: ...
    def get_task(self, task_id: str) -> Task | None: ...
    def update_task(self, task_id: str, changes: dict) -> Task | None: ...
    def courses(self) -> list[Course]: ...
    def clear(self) -> None: ...


class InMemoryRepository:
    """Good enough to demo and test; deliberately not good enough to ship."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._courses: dict[str, Course] = {}

    def save_result(self, result: ExtractionResult) -> None:
        self._courses[result.course.code] = result.course
        for task in result.tasks:
            self._tasks[task.id] = task

    def all_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, changes: dict) -> Task | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        # Validate through the model so a bad edit is rejected, not stored.
        updated = task.model_copy(update=changes)
        Task.model_validate(updated.model_dump())
        self._tasks[task_id] = updated
        return updated

    def courses(self) -> list[Course]:
        return list(self._courses.values())

    def clear(self) -> None:
        self._tasks.clear()
        self._courses.clear()
