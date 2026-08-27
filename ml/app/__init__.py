"""Application factory.

`create_app()` exists so the ML service can be run standalone for the demo.
The real backend should skip it and register the blueprint on their own app:

    from ml.app.routes import syllabus_bp
    app.register_blueprint(syllabus_bp)
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from .config import settings
from .routes import syllabus_bp
from .storage import InMemoryRepository, Repository

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(repository: Repository | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_bytes
    app.config["TESTING"] = testing
    app.extensions["syllabus_repo"] = repository or InMemoryRepository()

    try:
        from flask_cors import CORS

        CORS(app)  # the frontend runs on a different port during development
    except ImportError:  # pragma: no cover
        logging.getLogger(__name__).warning("flask-cors missing; CORS disabled")

    app.register_blueprint(syllabus_bp)

    @app.get("/")
    def demo_page():
        return send_from_directory(STATIC_DIR, "demo.html")

    @app.errorhandler(413)
    def too_large(_):
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        return jsonify({"error": f"file too large (limit {limit_mb} MB)"}), 413

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "not found"}), 404

    return app
