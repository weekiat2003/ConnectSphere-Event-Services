"""Tests for GET /api/health, the endpoint the CD pipeline's smoke test probes."""
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from app.extensions import db


def test_health_reports_ok_when_database_is_reachable(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok", "database": "ok"}


def test_health_needs_no_login(client):
    # The smoke test calls this before anyone has logged in.
    res = client.get("/api/health")
    assert res.status_code != 401


def test_health_is_503_when_database_is_unreachable(client):
    with patch.object(
        db.session, "execute", side_effect=OperationalError("SELECT 1", {}, Exception("down"))
    ):
        res = client.get("/api/health")
    assert res.status_code == 503
    assert res.get_json()["status"] == "error"
