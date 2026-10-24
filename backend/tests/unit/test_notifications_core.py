"""Tests for the shared notification plumbing (core.py + routes.py).

These must keep passing whatever story you are working on.
"""
import pytest

from app.extensions import db
from app.models.notification import TYPE_ORGANISER_UPDATE, Notification
from app.notifications.services import core


def test_notify_adds_but_does_not_commit(app, organiser):
    core.notify(organiser, TYPE_ORGANISER_UPDATE, "Title", "Body")
    assert Notification.query.count() == 1  # visible in this session (autoflush)
    db.session.rollback()
    assert Notification.query.count() == 0  # caller's rollback discards it


def test_notify_rejects_unknown_type(app, organiser):
    with pytest.raises(core.NotificationError):
        core.notify(organiser, "not_a_type", "Title", "Body")


def test_notify_role_reaches_each_active_user_once(app, make_user):
    a = make_user("v1@test.com", ["venue_staff"])
    b = make_user("v2@test.com", ["venue_staff"])
    make_user("other@test.com", ["attendee"])
    created = core.notify_role("venue_staff", TYPE_ORGANISER_UPDATE, "T", "M")
    db.session.commit()
    assert sorted(n.recipient_id for n in created) == sorted([a, b])


def test_notify_users_ignores_duplicates_and_none(app, organiser, coordinator):
    created = core.notify_users([organiser, organiser, None, coordinator], TYPE_ORGANISER_UPDATE, "T", "M")
    assert len(created) == 2


def test_inbox_routes(client, app, organiser, coordinator, auth_header):
    core.notify(organiser, TYPE_ORGANISER_UPDATE, "First", "Body", link="/events/1")
    core.notify(organiser, TYPE_ORGANISER_UPDATE, "Second", "Body")
    other = core.notify(coordinator, TYPE_ORGANISER_UPDATE, "Not yours", "Body")
    db.session.commit()
    other_id = other.id
    headers = auth_header("organiser@test.com")

    res = client.get("/api/notifications", headers=headers)
    assert res.status_code == 200
    assert {n["title"] for n in res.get_json()} == {"First", "Second"}

    assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 2

    first_id = next(n["id"] for n in res.get_json() if n["title"] == "First")
    res = client.post(f"/api/notifications/{first_id}/read", headers=headers)
    assert res.status_code == 200 and res.get_json()["isRead"] is True
    assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 1

    unread = client.get("/api/notifications?unread=true", headers=headers).get_json()
    assert [n["title"] for n in unread] == ["Second"]

    # Someone else's notification looks like it doesn't exist.
    assert client.post(f"/api/notifications/{other_id}/read", headers=headers).status_code == 404

    assert client.post("/api/notifications/read-all", headers=headers).get_json()["updated"] == 1
    assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 0


def test_inbox_requires_login(client):
    assert client.get("/api/notifications").status_code == 401
