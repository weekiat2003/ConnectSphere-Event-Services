from flask import Flask

from app.config import config_by_name
from app.extensions import db, migrate, jwt, cors


def create_app(config_name="development"):
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(
    app,
    resources={
        r"/api/*": {
            "origins": ["http://localhost:5173"],
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    },
    supports_credentials=False,
)

    # Import models so Flask-Migrate can detect them
    from app.models import user, event, venue, equipment, change_request  # noqa: F401

    from app.auth.routes import auth_bp
    from app.equipment.routes import equipment_bp
    from app.events.routes import events_bp
    from app.venues.routes import venues_bp
    from app.change_requests.routes import change_requests_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(equipment_bp, url_prefix="/api/equipment")
    app.register_blueprint(events_bp, url_prefix="/api/events")
    app.register_blueprint(venues_bp, url_prefix="/api/venues")
    app.register_blueprint(change_requests_bp, url_prefix="/api/change-requests")

    from app.common.errors import register_error_handlers
    register_error_handlers(app)

    # Run with `flask process-holds`, scheduled externally every five minutes.
    # No background thread inside Flask (avoids debug-reloader duplicates).
    @app.cli.command("process-holds")
    def process_holds_command():
        from app.venues.services.booking import expire_due_holds
        count = expire_due_holds()
        print(f"Expired {count} tentative hold(s).")

    @app.get("/api/health")
    def health():
        """Liveness check used by the CD pipeline's smoke test.

        Also pings the database, so a release that starts but cannot reach
        its database reports 503 instead of looking healthy.
        """
        from flask import jsonify
        from sqlalchemy import text

        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            return jsonify(status="error", database="unreachable"), 503
        return jsonify(status="ok", database="ok"), 200

    return app