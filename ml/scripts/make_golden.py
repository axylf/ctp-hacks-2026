"""Regenerate the golden snapshot and the /api/demo/sample payload.

Run this ONLY when you intend to change the expected output, and read the diff
before committing it — that diff is the whole point of the snapshot.

    uv run python ml/scripts/make_golden.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Runnable directly (uv run python ml/scripts/make_golden.py) as well as via pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.app.pipeline import PipelineOptions, process_pdf  # noqa: E402
from ml.tests.conftest import TERM_END, TERM_START, TODAY  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests" / "fixtures" / "syllabi" / "intro_to_networks_spring2026.pdf"
TARGET = ROOT / "tests" / "fixtures" / "golden" / "intro_to_networks.json"


def main() -> None:
    result = process_pdf(
        SOURCE.read_bytes(),
        PipelineOptions(
            term_start=TERM_START, term_end=TERM_END, today=TODAY, use_gemini=False
        ),
    )
    payload = result.model_dump(mode="json")
    payload["meta"]["processing_ms"] = 0   # not reproducible; zero it deliberately

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {TARGET.relative_to(ROOT.parent)}")
    print(f"  {len(payload['tasks'])} tasks, "
          f"{len(payload['workload_analysis']['windows'])} windows, "
          f"{len(payload['recommendations'])} recommendations")


if __name__ == "__main__":
    main()
