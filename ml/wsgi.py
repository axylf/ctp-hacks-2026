"""Standalone entry point for the ML service.

    uv run python ml/wsgi.py          # http://127.0.0.1:5001

The real Flask backend should NOT use this. It should register the blueprint on
its own app instead:

    from ml.app.routes import syllabus_bp
    app.register_blueprint(syllabus_bp)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    from ml.app.config import settings

    print("Syllabus Intelligence Engine  ->  http://127.0.0.1:5001")
    print(
        "  extractor:",
        f"Gemini ({settings.gemini_model})" if settings.gemini_enabled
        else "offline regex (add GEMINI_API_KEY to .env to enable Gemini)",
    )
    app.run(host="127.0.0.1", port=5001, debug=False)
