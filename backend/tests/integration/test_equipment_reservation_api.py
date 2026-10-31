from datetime import datetime

import pytest

from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement
from app.models.user import User

URL = "/api/equipment/reservations"
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
def setup_event(organiser, make_event):
    def _setup(quantity=4, status="approved", equipment_type="Projector"):
        event_id = make_event(organiser)
        db.session.get(Event, event_id).status = status
        req = EventEquipmentRequirement(
            event_id=event_id, equipment_type=equipment_type, quantity=quantity
        )
        db.session.add(req)
        db.session.commit()
        return event_id, req.id
    return _setup


def payload(event_id, requirement_id, item_id, start=START, end=END):
    return {
        "eventId": event_id,
        "requirementId": requirement_id,
        "equipmentItemId": item_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def reserve(client, headers, body):
    return client.post(URL, json=body, headers=headers)


def count():
    return EquipmentReservation.query.count()


def requirement_status(requirement_id):
    db.session.expire_all()
    return db.session.get(EventEquipmentRequirement, requirement_id).status


def free_quantity(client, headers, item_id):
    res = client.get(
        f"/api/equipment/items/{item_id}/availability"
        f"?start={START.isoformat()}&end={END.isoformat()}&quantity=1",
        headers=headers,
    )
    return res.get_json()["freeQuantity"]


def test_reserve_creates_reservation_and_confirms_requirement(client, tech_headers, item, setup_event):
    event_id, req_id = setup_event(quantity=4)

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == 201
    body = res.get_json()
    assert body["id"] and body["quantity"] == 4 and body["status"] == "reserved"
    assert body["eventId"] == event_id and body["equipmentItemId"] == item
    assert requirement_status(req_id) == "confirmed"


def test_reservation_matches_equipment_type_case_insensitively_and_trims(
    client, tech_headers, item, setup_event
):
    event_id, req_id = setup_event(equipment_type=" projector ")

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == 201
    db.session.expire_all()
    assert EquipmentReservation.query.one().equipment_requirement_id == req_id


def test_reservation_rejects_wrong_equipment_type(client, tech_headers, item, setup_event):
    event_id, req_id = setup_event(equipment_type="Camera")

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == 400
    assert res.get_json()["error"] == "This item doesn't match the requested equipment type."
    assert count() == 0


@pytest.mark.parametrize(
    "quantity,error_message",
    [(5, "cannot exceed"), (None, "positive whole number")],
)
def test_reservation_quantity_must_be_valid_and_within_requirement(
    client, tech_headers, item, setup_event, quantity, error_message
):
    event_id, req_id = setup_event(quantity=4)
    body = payload(event_id, req_id, item)
    body["quantity"] = quantity

    res = reserve(client, tech_headers, body)

    assert res.status_code == 400
    assert error_message in res.get_json()["error"]
    assert count() == 0


def test_reserve_records_creator_period_and_leaves_total_unchanged(client, tech_headers, item, setup_event):
    event_id, req_id = setup_event(quantity=4)

    reserve(client, tech_headers, payload(event_id, req_id, item))

    db.session.expire_all()
    record = EquipmentReservation.query.one()
    tech = User.query.filter_by(email="tech@test.com").first()
    assert record.created_by == tech.id
    assert record.created_at is not None
    assert record.equipment_requirement_id == req_id
    assert record.start_datetime == START and record.end_datetime == END
    assert db.session.get(EquipmentItem, item).total_quantity == 10


def test_not_enough_stock_returns_400_naming_item(client, tech_headers, item, setup_event):
    event_id, req_id = setup_event(quantity=11)

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == 400
    assert "Projector" in res.get_json()["error"]
    assert count() == 0
    assert requirement_status(req_id) == "requested"


@pytest.mark.parametrize("total,expected", [(4, 201), (5, 201), (3, 400)])
def test_boundary_around_requested_quantity(client, tech_headers, item, setup_event, total, expected):
    db.session.get(EquipmentItem, item).total_quantity = total
    db.session.commit()
    event_id, req_id = setup_event(quantity=4)

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == expected


def test_exactly_q_free_leaves_zero_free_afterwards(client, tech_headers, item, setup_event):
    db.session.get(EquipmentItem, item).total_quantity = 4
    db.session.commit()
    event_id, req_id = setup_event(quantity=4)

    assert reserve(client, tech_headers, payload(event_id, req_id, item)).status_code == 201
    assert free_quantity(client, tech_headers, item) == 0


def test_reserving_same_requirement_twice_is_rejected(client, tech_headers, item, setup_event):
    event_id, req_id = setup_event(quantity=2)
    body = payload(event_id, req_id, item)

    assert reserve(client, tech_headers, body).status_code == 201
    second = reserve(client, tech_headers, body)

    assert second.status_code == 400
    assert count() == 1


@pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "rejected", "cancelled", "completed"])
def test_ineligible_event_status_is_rejected(client, tech_headers, item, setup_event, status):
    event_id, req_id = setup_event(status=status)

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == 400
    assert count() == 0


@pytest.mark.parametrize("status", ["approved", "planning", "confirmed"])
def test_eligible_event_status_is_accepted(client, tech_headers, item, setup_event, status):
    event_id, req_id = setup_event(status=status)

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == 201


@pytest.mark.parametrize("missing", ["event", "requirement", "item"])
def test_missing_event_requirement_or_item_returns_404(client, tech_headers, item, setup_event, missing):
    event_id, req_id = setup_event()
    body = payload(event_id, req_id, item)
    body[{"event": "eventId", "requirement": "requirementId", "item": "equipmentItemId"}[missing]] = 99999

    res = reserve(client, tech_headers, body)

    assert res.status_code == 404
    assert count() == 0


def test_requirement_of_another_event_returns_400(client, tech_headers, item, setup_event):
    event_a, _ = setup_event()
    _, other_req = setup_event()

    res = reserve(client, tech_headers, payload(event_a, other_req, item))

    assert res.status_code == 400
    assert count() == 0


@pytest.mark.parametrize("status", ["damaged", "maintenance", "retired"])
def test_inactive_item_is_rejected(client, tech_headers, item, setup_event, status):
    db.session.get(EquipmentItem, item).status = status
    db.session.commit()
    event_id, req_id = setup_event()

    res = reserve(client, tech_headers, payload(event_id, req_id, item))

    assert res.status_code == 400
    assert "not active" in res.get_json()["error"]
    assert count() == 0


@pytest.mark.parametrize("change", [
    {"start": None},
    {"end": None},
    {"start": "not-a-date"},
    {"end": "2026-12-01T10:00:00"},
    {"end": "2026-12-01T09:00:00"},
])
def test_invalid_period_returns_400(client, tech_headers, item, setup_event, change):
    event_id, req_id = setup_event()
    body = payload(event_id, req_id, item)
    for key, value in change.items():
        if value is None:
            del body[key]
        else:
            body[key] = value

    res = reserve(client, tech_headers, body)

    assert res.status_code == 400
    assert count() == 0


def test_second_reservation_for_last_units_is_rejected(client, tech_headers, item, setup_event):
    first_event, first_req = setup_event(quantity=6)
    second_event, second_req = setup_event(quantity=6)

    first = reserve(client, tech_headers, payload(first_event, first_req, item))
    second = reserve(client, tech_headers, payload(second_event, second_req, item))

    assert first.status_code == 201
    assert second.status_code == 400
    assert count() == 1
    assert free_quantity(client, tech_headers, item) == 4


def test_overlapping_reservation_exceeding_stock_is_rejected(
    client, tech_headers, item, setup_event
):
    db.session.get(EquipmentItem, item).total_quantity = 5
    db.session.commit()
    first_event, first_req = setup_event(quantity=4)
    second_event, second_req = setup_event(quantity=2)

    assert reserve(client, tech_headers, payload(first_event, first_req, item)).status_code == 201
    second = reserve(client, tech_headers, payload(second_event, second_req, item))

    assert second.status_code == 400
    assert count() == 1


def test_non_overlapping_reservation_succeeds_when_other_slot_is_full(
    client, tech_headers, item, setup_event
):
    db.session.get(EquipmentItem, item).total_quantity = 4
    db.session.commit()
    first_event, first_req = setup_event(quantity=4)
    second_event, second_req = setup_event(quantity=4)
    later_start = END
    later_end = datetime(2026, 12, 1, 12, 0)

    assert reserve(client, tech_headers, payload(first_event, first_req, item)).status_code == 201
    second = reserve(
        client,
        tech_headers,
        payload(second_event, second_req, item, later_start, later_end),
    )

    assert second.status_code == 201
    assert count() == 2


@pytest.mark.parametrize("email,role", [
    ("coord@test.com", "event_coordinator"),
    ("org@test.com", "event_organiser"),
    ("att@test.com", "attendee"),
])
def test_other_roles_are_denied(client, make_user, auth_header, item, setup_event, email, role):
    make_user(email, [role])
    event_id, req_id = setup_event()

    res = reserve(client, auth_header(email), payload(event_id, req_id, item))

    assert res.status_code == 403
    assert count() == 0


def test_unauthenticated_is_denied(client, item, setup_event):
    event_id, req_id = setup_event()

    res = client.post(URL, json=payload(event_id, req_id, item))

    assert res.status_code == 401
    assert count() == 0