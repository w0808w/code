from __future__ import annotations

from flask import Flask


def enable_cors(app: Flask) -> None:
    """Very simple CORS headers for dev. Replace with flask-cors if needed."""
    @app.after_request
    def add_cors_headers(response):  # type: ignore[override]
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response


