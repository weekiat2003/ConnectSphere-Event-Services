from datetime import datetime

import pytest

from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import EventEquipmentRequirement

BASE = "/api/equipment/items"
START = datetime(2026, 12, 1, 10, 0)
END = datetime(2026, 12, 1, 11, 0)


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


@pytest.fixture()
def reserve(organiser, make_event):
    def _reserve(item_id, qty, start=START, end=END, status="reserved"):
        r = EquipmentReservation(
            event_id=make_event(organiser), equipment_item_id=item_id,
            quantity=qty, start_datetime=start, end_datetime=end, status=status,
        )
        db.session.add(r)
        db.session.commit()
        return r.id
    return _reserve


def get(client, headers, item_id, query):
    return client.get(f"{BASE}/{item_id}/availability?{query}", headers=headers)


def q(quantity=1, start=START, end=END):
    return f"start={start.isoformat()}&end={end.isoformat()}&quantity={quantity}"


def test_available_shows_free_quantity(client, tech_headers, item):  # AC1
    body = get(client, tech_headers, item, q(3)).get_json()
    assert body["available"] is True
    assert body["freeQuantity"] == 10 and body["totalQuantity"] == 10


def test_not_available_shows_shortfall(client, tech_headers, item, reserve):  # AC2
    reserve(item, 8)
    body = get(client, tech_headers, item, q(5)).get_json()
    assert body["available"] is False
    assert body["freeQuantity"] == 2 and body["shortfall"] == 3


@pytest.mark.parametrize("wanted,expected", [(4, True), (5, True), (6, False)])
def test_boundary_around_free_quantity(client, tech_headers, item, reserve, wanted, expected):  # AC3
    reserve(item, 5)
    body = get(client, tech_headers, item, q(wanted)).get_json()
    assert body["freeQuantity"] == 5
    assert body["available"] is expected


@pytest.mark.parametrize("query,field", [
    ("end=2026-12-01T11:00:00&quantity=1", "start"),
    ("start=2026-12-01T10:00:00&quantity=1", "end"),
    ("start=not-a-date&end=2026-12-01T11:00:00&quantity=1", "start"),
    ("start=2026-12-01T10:00:00&end=2026-12-01T10:00:00&quantity=1", "end"),
    ("start=2026-12-01T10:00:00&end=2026-12-01T09:00:00&quantity=1", "end"),
    ("start=2026-12-01T10:00:00&end=2026-12-01T11:00:00&quantity=0", "quantity"),
    ("start=2026-12-01T10:00:00&end=2026-12-01T11:00:00&quantity=-2", "quantity"),
    ("start=2026-12-01T10:00:00&end=2026-12-01T11:00:00&quantity=abc", "quantity"),
    ("start=2026-12-01T10:00:00&end=2026-12-01T11:00:00&quantity=1.5", "quantity"),
])
def test_invalid_input_returns_400_naming_field(client, tech_headers, item, query, field):  # AC4
    res = get(client, tech_headers, item, query)
    body = res.get_json()
    assert res.status_code == 400
    assert field in body["error"]
    assert "available" not in body


def test_unknown_item_returns_404(client, tech_headers):  # AC5
    res = get(client, tech_headers, 9999, q())
    assert res.status_code == 404
    assert res.get_json()["error"] == "Equipment item not found"


@pytest.mark.parametrize("status", ["damaged", "maintenance", "retired"])
def test_inactive_item_not_available_with_reason_and_zero_free(client, tech_headers, item, status):  # AC6
    db.session.get(EquipmentItem, item).status = status
    db.session.commit()
    body = get(client, tech_headers, item, q()).get_json()
    assert body["available"] is False
    assert body["freeQuantity"] == 0
    assert status in body["reason"]


def test_coordinator_allowed(client, make_user, auth_header, item):  # AC8
    make_user("coord@test.com", ["event_coordinator"])
    assert get(client, auth_header("coord@test.com"), item, q()).status_code == 200


@pytest.mark.parametrize("email,role", [
    ("org@test.com", "event_organiser"),
    ("att@test.com", "attendee"),
    ("venue@test.com", "venue_staff"),
])
def test_other_roles_denied(client, make_user, auth_header, item, email, role):  # AC8
    make_user(email, [role])
    assert get(client, auth_header(email), item, q()).status_code == 403


def test_unauthenticated_denied(client, item):  # AC8
    assert client.get(f"{BASE}/{item}/availability?{q()}").status_code == 401


def test_check_is_read_only(client, tech_headers, item, reserve):  # AC9
    reserve(item, 3)
    get(client, tech_headers, item, q(2))
    db.session.expire_all()
    assert EquipmentReservation.query.count() == 1
    assert db.session.get(EquipmentItem, item).total_quantity == 10


def test_result_shows_item_quantity_period_free_total(client, tech_headers, item):  # AC10
    body = get(client, tech_headers, item, q(2)).get_json()
    for key in ("item", "requestedQuantity", "start", "end", "freeQuantity", "totalQuantity"):
        assert key in body
    assert body["requestedQuantity"] == 2

EVENT_BASE = "/api/equipment/events"


def period():
    return f"start={START.isoformat()}&end={END.isoformat()}"


def add_requirement(event_id, equipment_type, quantity):
    r = EventEquipmentRequirement(event_id=event_id, equipment_type=equipment_type, quantity=quantity)
    db.session.add(r)
    db.session.commit()
    return r.id


def add_item(name, total):
    db.session.add(EquipmentItem(name=name, total_quantity=total))
    db.session.commit()


def check_event(client, headers, event_id, query=None):
    return client.get(f"{EVENT_BASE}/{event_id}/availability?{query or period()}", headers=headers)


def test_event_check_gives_each_requirement_its_own_result(client, tech_headers, item, organiser, make_event):  # AC7
    add_item("Microphone", 2)
    event_id = make_event(organiser)
    add_requirement(event_id, "Projector", 4)
    add_requirement(event_id, "Microphone", 2)
    res = check_event(client, tech_headers, event_id)
    body = res.get_json()
    assert res.status_code == 200
    assert len(body["results"]) == 2
    by_type = {r["type"]: r for r in body["results"]}
    assert by_type["Projector"]["freeQuantity"] == 10
    assert by_type["Microphone"]["requestedQuantity"] == 2
    assert body["available"] is True


def test_event_check_not_available_if_any_requirement_fails(client, tech_headers, item, organiser, make_event):  # AC7
    add_item("Microphone", 2)
    event_id = make_event(organiser)
    add_requirement(event_id, "Projector", 4)
    add_requirement(event_id, "Microphone", 3)
    body = check_event(client, tech_headers, event_id).get_json()
    by_type = {r["type"]: r for r in body["results"]}
    assert by_type["Projector"]["available"] is True
    assert by_type["Microphone"]["available"] is False
    assert by_type["Microphone"]["shortfall"] == 1
    assert body["available"] is False


def test_event_requirement_without_catalogue_item_is_not_available(client, tech_headers, organiser, make_event):  # AC7
    event_id = make_event(organiser)
    add_requirement(event_id, "Laser Pointer", 1)
    body = check_event(client, tech_headers, event_id).get_json()
    assert body["results"][0]["available"] is False
    assert "Laser Pointer" in body["results"][0]["reason"]
    assert body["available"] is False


def test_event_check_unknown_event_returns_404(client, tech_headers):  # AC7
    res = check_event(client, tech_headers, 9999)
    assert res.status_code == 404
    assert res.get_json()["error"] == "Event not found"


def test_event_check_missing_period_returns_400(client, tech_headers, organiser, make_event):  # AC7
    res = check_event(client, tech_headers, make_event(organiser), query="end=2026-12-01T11:00:00")
    assert res.status_code == 400
    assert "start" in res.get_json()["error"]


def test_event_check_organiser_denied(client, make_user, auth_header, organiser, make_event):  # AC7, AC8
    make_user("org2@test.com", ["event_organiser"])
    res = check_event(client, auth_header("org2@test.com"), make_event(organiser))
    assert res.status_code == 403