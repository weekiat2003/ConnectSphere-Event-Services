import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.user import Organisation, Role, User  # noqa: E402
from datetime import date  # noqa: E402
from app.models.event import Event  # noqa: E402

from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_integer_for_sqlite(type_, compiler, **kw):
    """
    SQLite only auto-generates a primary key when its type compiles to
    exactly INTEGER. Our schema uses BIGINT UNSIGNED everywhere (matching
    MySQL), which breaks autoincrement under SQLite-backed tests. This
    only affects the SQLite test dialect -- the real MySQL schema is untouched.
    """
    return "INTEGER"


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        db.create_all()
        for name in (
            "event_organiser",
            "event_coordinator",
            "venue_staff",
            "technical_support_staff",
            "safety_officer",
            "attendee",
        ):
            db.session.add(Role(name=name))
        db.session.commit()
        yield application
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def organiser(app):
    with app.app_context():
        org = Organisation(name="Test Org")
        db.session.add(org)
        db.session.commit()
        user = User(
            name="Test Organiser",
            email="organiser@test.com",
            password_hash=generate_password_hash("password"),
            organisation_id=org.id,
        )
        user.roles = [Role.query.filter_by(name="event_organiser").first()]
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture()
def coordinator(app):
    with app.app_context():
        user = User(
            name="Test Coordinator",
            email="coordinator@test.com",
            password_hash=generate_password_hash("password"),
        )
        user.roles = [Role.query.filter_by(name="event_coordinator").first()]
        db.session.add(user)
        db.session.commit()
        return user.id

@pytest.fixture()
def make_user(app):
    def _make(email, role_names, name=None):
        user = User(
            name=name or email.split("@")[0],
            email=email,
            password_hash=generate_password_hash("password"),
        )
        user.roles = [Role.query.filter_by(name=r).first() for r in role_names]
        db.session.add(user)
        db.session.commit()
        return user.id
    return _make


@pytest.fixture()
def auth_header(client):
    def _login(email, password="password"):
        res = client.post("/api/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.get_json()
        return {"Authorization": f"Bearer {res.get_json()['accessToken']}"}
    return _login


@pytest.fixture()
def make_event(app):
    """Inserts an event directly at a given status, bypassing the state
    machine on purpose so we can test display/visibility in isolation."""
    def _make(organiser_id, status="draft", **fields):
        defaults = dict(
            name="Test Event", purpose="Testing", description="A test event",
            proposed_date=date(2026, 12, 1), expected_attendance=50,
        )
        defaults.update(fields)
        event = Event(organiser_id=organiser_id, status=status, **defaults)
        db.session.add(event)
        db.session.commit()
        return event.id
    return _make