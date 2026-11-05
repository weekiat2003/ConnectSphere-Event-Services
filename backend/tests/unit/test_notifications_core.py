"""Tests for the shared notification plumbing (core.py + routes.py).

These must keep passing whatever story you are working on.
"""
import pytest

from app.extensions import db
from app.models.notification import TYPE_ORGANISER_UPDATE, Notification
from app.models.user import User
from app.notifications.services import core


def test_notify_adds_but_does_not_commit(app, organiser):
    core.notify(organiser, TYPE_ORGANISER_UPDATE, "Title", "Body")
    assert Notification.query.count() == 1  # visible in this session (autoflush)
    db.session.rollback()
    assert Notification.query.count() == 0  # caller's rollback discards it


def test_notify_rejects_unknown_type(app, organiser):
    with pytest.raises(core.NotificationError):
        core.notify(organiser, "not_a_type", "Title", "Body")


@pytest.mark.parametrize(
    "title,message",
    [("", "Body"), ("Title", "")],
)
def test_notify_requires_title_and_message(app, organiser, title, message):
    with pytest.raises(
        core.NotificationError, match="A notification needs a title and a message"
    ):
        core.notify(organiser, TYPE_ORGANISER_UPDATE, title, message)

    assert Notification.query.count() == 0


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


def test_clear_notifications_updates_unread_read_and_extra_data(app, organiser):
    unread = core.notify(
        organiser, TYPE_ORGANISER_UPDATE, "Unread", "Body",
        event_id=17, data={"existing": "value"},
    )
    already_read = core.notify(
        organiser, TYPE_ORGANISER_UPDATE, "Read", "Body",
        event_id=17, data={"keep": True},
    )
    unrelated = core.notify(
        organiser, TYPE_ORGANISER_UPDATE, "Other event", "Body", event_id=18,
    )
    db.session.commit()
    already_read.is_read = True
    already_read.read_at = already_read.created_at
    db.session.commit()
    read_at = already_read.read_at

    cleared = core.clear_notifications(TYPE_ORGANISER_UPDATE, 17)

    assert cleared == 2
    db.session.flush()
    db.session.refresh(unread)
    db.session.refresh(already_read)
    db.session.refresh(unrelated)
    assert unread.cleared_at is not None
    assert unread.is_read is True
    assert unread.read_at is not None
    assert already_read.cleared_at is not None
    assert already_read.is_read is True
    assert already_read.read_at == read_at
    assert unrelated.cleared_at is None
    assert unread.data == {"existing": "value"}
    assert already_read.data == {"keep": True}

    assert core.clear_notifications(TYPE_ORGANISER_UPDATE, 17) == 0


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

def test_notify_role_skips_inactive_users(app, make_user):
    active = make_user("v1@test.com", ["venue_staff"])
    inactive = make_user("v2@test.com", ["venue_staff"])
    db.session.get(User, inactive).is_active = False
    db.session.commit()
    created = core.notify_role("venue_staff", TYPE_ORGANISER_UPDATE, "T", "M")
    assert [n.recipient_id for n in created] == [active]


def test_clear_notifications_merges_extra_data(app, organiser):
    notification = core.notify(
        organiser, TYPE_ORGANISER_UPDATE, "Title", "Body",
        event_id=23, data={"existing": "value"},
    )
    db.session.commit()

    assert core.clear_notifications(
        TYPE_ORGANISER_UPDATE, 23, {"resolution": "done"}
    ) == 1

    db.session.flush()
    db.session.refresh(notification)
    assert notification.data == {"existing": "value", "resolution": "done"}
    assert notification.is_read is True
    assert notification.cleared_at is not None


def test_mark_read_reports_missing_notification(app, organiser):
    with pytest.raises(LookupError, match="Notification not found"):
        core.mark_read(999999, organiser)


def test_mark_read_keeps_existing_read_timestamp(app, organiser):
    notification = core.notify(organiser, TYPE_ORGANISER_UPDATE, "Title", "Body")
    db.session.commit()
    notification.is_read = True
    notification.read_at = notification.created_at
    db.session.commit()
    read_at = notification.read_at

    result = core.mark_read(notification.id, organiser)

    assert result.id == notification.id
    assert result.is_read is True
    assert result.read_at == read_at


def test_inbox_invalid_limit_uses_default(
    client, organiser, auth_header, monkeypatch
):
    from unittest.mock import Mock

    list_items = Mock(return_value=[])
    monkeypatch.setattr(core, "list_for_user", list_items)
    headers = auth_header("organiser@test.com")

    response = client.get(
        "/api/notifications?limit=invalid",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json() == []
    list_items.assert_called_once_with(
        organiser,
        unread_only=False,
        limit=50,
    )