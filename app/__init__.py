from flask import Flask


def create_app() -> Flask:
    """Application factory (optional use)."""
    app = Flask(__name__)
    return app


