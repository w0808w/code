from __future__ import annotations

from flask import Flask

from . import create_app
from .config import get_server_port
from .routes import api_bp
from .cors import enable_cors
from .db import ensure_tables


def build_app() -> Flask:
    app = create_app()
    app.register_blueprint(api_bp)
    enable_cors(app)
    # Best-effort DB init on boot as well (complements before_first_request hook)
    try:
        ensure_tables()
    except Exception:
        pass
    return app

app = build_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=get_server_port(), debug=False)