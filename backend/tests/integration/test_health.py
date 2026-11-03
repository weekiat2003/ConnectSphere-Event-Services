"""Tests for GET /api/health, the endpoint the CD pipeline's smoke test probes."""
from unittest.mock import patch

import pytest
from flask import abort

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


@pytest.mark.parametrize(
    ("status_code", "message"),
    [(400, "Bad request"), (403, "Forbidden"), (404, "Resource not found"),
     (500, "Internal server error")],
)
def test_registered_error_handlers_return_json(app, client, status_code, message):
    def trigger_error():
        abort(status_code)

    app.add_url_rule("/test-error-handler", view_func=trigger_error)
    response = client.get("/test-error-handler")

    assert response.status_code == status_code
    assert response.is_json
    assert response.get_json() == {"error": message}
