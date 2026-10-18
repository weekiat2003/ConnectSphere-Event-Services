from datetime import timedelta

import pytest

from app.common.time import utcnow
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation

BASE = "/api/equipment/items"


@pytest.fixture()
def tech_headers(make_user, auth_header):
    make_user("tech@test.com", ["technical_support_staff"])
    return auth_header("tech@test.com")


@pytest.fixture()
def item(app):
    it = EquipmentItem(name="Projector", total_quantity=10)
    db.session.add(it)
    db.session.commit()
    return it.id


def mark(client, headers, item_id, reason):
    return client.post(f"{BASE}/{item_id}/mark-unavailable", json={"reason": reason}, headers=headers)


def fresh(item_id):
    db.session.expire_all()
    return db.session.get(EquipmentItem, item_id)


def test_mark_damaged_sets_status_and_keeps_quantity(client, tech_headers, item):  # AC1, AC10
    res = mark(client, tech_headers, item, "damaged")
    assert res.status_code == 200
    assert res.get_json()["status"] == "damaged"
    assert fresh(item).status == "damaged"
    assert fresh(item).total_quantity == 10


@pytest.mark.parametrize("payload", [{}, {"reason": ""}, {"reason": "broken"}])
def test_invalid_reason_returns_400_status_unchanged(client, tech_headers, item, payload):  # AC3
    res = client.post(f"{BASE}/{item}/mark-unavailable", json=payload, headers=tech_headers)
    assert res.status_code == 400
    assert fresh(item).status == "active"


def test_remark_with_different_reason_keeps_latest(client, tech_headers, item):  # AC4
    assert mark(client, tech_headers, item, "damaged").status_code == 200
    assert mark(client, tech_headers, item, "maintenance").status_code == 200
    assert fresh(item).status == "maintenance"


def test_unavailable_item_reports_not_available_with_reason(client, tech_headers, item):  # AC2
    mark(client, tech_headers, item, "damaged")
    start = (utcnow() + timedelta(days=1)).replace(tzinfo=None)
    end = start + timedelta(hours=2)
    res = client.get(
        f"{BASE}/{item}/availability?start={start.isoformat()}&end={end.isoformat()}&quantity=1",
        headers=tech_headers,
    )
    body = res.get_json()
    assert res.status_code == 200
    assert body["available"] is False
    assert "damaged" in body["reason"]


def test_affected_reservations_listed_not_cancelled(client, tech_headers, item, organiser, make_event):  # AC5, AC10
    event_id = make_event(organiser)
    start = utcnow() + timedelta(days=30)
    r = EquipmentReservation(
        event_id=event_id, equipment_item_id=item, quantity=2,
        start_datetime=start, end_datetime=start + timedelta(hours=3), status="reserved",
    )
    db.session.add(r)
    db.session.commit()
    rid = r.id
    body = mark(client, tech_headers, item, "damaged").get_json()
    assert [a["id"] for a in body["affectedReservations"]] == [rid]
    db.session.expire_all()
    assert db.session.get(EquipmentReservation, rid).status == "reserved"


@pytest.mark.parametrize("action", ["mark-unavailable", "mark-active"])
def test_missing_item_returns_404(client, tech_headers, action):  # AC6
    res = client.post(f"{BASE}/9999/{action}", json={"reason": "damaged"}, headers=tech_headers)
    assert res.status_code == 404
    assert res.get_json()["error"] == "Equipment item not found"


def test_restore_and_repeat_restore(client, tech_headers, item):  # AC7, AC8
    mark(client, tech_headers, item, "maintenance")
    assert client.post(f"{BASE}/{item}/mark-active", headers=tech_headers).status_code == 200
    assert fresh(item).status == "active"
    assert client.post(f"{BASE}/{item}/mark-active", headers=tech_headers).status_code == 200
    assert fresh(item).status == "active"


@pytest.mark.parametrize("email,roles", [
    ("coord@test.com", ["event_coordinator"]),
    ("org@test.com", ["event_organiser"]),
])
@pytest.mark.parametrize("action", ["mark-unavailable", "mark-active"])
def test_other_roles_denied(client, make_user, auth_header, item, email, roles, action):  # AC9
    make_user(email, roles)
    res = client.post(f"{BASE}/{item}/{action}", json={"reason": "damaged"}, headers=auth_header(email))
    assert res.status_code == 403
    assert fresh(item).status == "active"


def test_unauthenticated_denied(client, item):  # AC9
    res = client.post(f"{BASE}/{item}/mark-unavailable", json={"reason": "damaged"})
    assert res.status_code == 401


def test_status_change_updates_updated_at(client, tech_headers, item):  # AC11
    it = fresh(item)
    old = utcnow() - timedelta(days=1)
    it.updated_at = old
    db.session.commit()
    mark(client, tech_headers, item, "damaged")
    assert fresh(item).updated_at > old