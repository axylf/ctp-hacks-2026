"""Central configuration. Every tunable threshold lives here so the eval harness
can sweep them without hunting constants scattered through the pipeline."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # --- Gemini -----------------------------------------------------------
    # The ONLY setup step: put GEMINI_API_KEY in .env (see .env.example).
    # With no key the pipeline runs the offline extractor instead, so every
    # endpoint and every test still works.
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    gemini_timeout_s: float = 60.0
    gemini_max_retries: int = 3

    # --- Database ---------------------------------------------------------
    # NOT used by the pipeline, which is stateless by design. This is here
    # for the seed/verify script and for whoever implements the real
    # Repository against Postgres.
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql://localhost:5432/syllabus_planner"
        )
    )

    # --- Routing (stage 2) ------------------------------------------------
    # chars-per-page below this means the PDF has no usable text layer
    text_density_threshold: int = 300

    # --- Vision preprocessing (stage 3) -----------------------------------
    blur_reject_below: float = 45.0      # Laplacian variance
    min_document_area_ratio: float = 0.20
    target_short_edge_px: int = 1600
    max_skew_search_deg: float = 15.0
    render_dpi: int = 200

    # --- Uploads ----------------------------------------------------------
    max_upload_bytes: int = 20 * 1024 * 1024
    max_scan_frames: int = 12

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)


settings = Settings()


# --- Priority scoring (stage 5) -------------------------------------------
PRIORITY_WEIGHTS = {"type": 0.35, "grade": 0.30, "proximity": 0.20, "week_load": 0.15}

TYPE_WEIGHT = {
    "final": 1.0, "midterm": 1.0, "exam": 1.0,
    "project": 0.85, "paper": 0.85,
    "presentation": 0.70,
    "assignment": 0.55,
    "quiz": 0.35,
    "reading": 0.15,
    "other": 0.30,
}

PRIORITY_CUTOFFS = [("critical", 0.75), ("high", 0.55), ("medium", 0.35)]

# --- Workload analysis (stage 6) ------------------------------------------
EFFORT_UNITS = {
    "exam": 5, "final": 5, "midterm": 5, "project": 5,
    "paper": 4, "presentation": 3, "assignment": 3,
    "quiz": 2, "reading": 1, "other": 2,
}

MAJOR_TYPES = {"exam", "final", "midterm", "project", "paper", "presentation"}

SEVERITY_RULES = [
    ("critical", 12.0, 3),
    ("heavy", 8.0, 2),
    ("moderate", 5.0, 1),
]

ESTIMATED_HOURS = {
    "final": 10, "midterm": 8, "exam": 8, "project": 12, "paper": 10,
    "presentation": 6, "assignment": 5, "quiz": 2, "reading": 2, "other": 3,
}
