"""ISP-65: release reserved equipment (manual release, event cancellation, requirement removal)."""
from datetime import datetime

import pytest

from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import EventEquipmentRequirement

START = datetime(2026, 12, 1, 10, 0)
END = datetime(2026, 12, 1, 11, 0)
REASON = "The client has cancelled their launch."


@pytest.fixture
def path(app):
    adapter = app.url_map.bind("localhost")
    return lambda endpoint, **values: adapter.build(endpoint, values)


@pytest.fixture
def tech(make_user, auth_header):
    make_user("tech65@test.com", ["technical_support_staff"])
    return auth_header("tech65@test.com")


@pytest.fixture
def coord(make_user):
    return make_user("coord65@test.com", ["event_coordinator"])


@pytest.fixture
def coord_headers(coord, auth_header):
    return auth_header("coord65@test.com")


@pytest.fixture
def item(app):
    it = EquipmentItem(name="Projector", total_quantity=10)
    db.session.add(it)
    db.session.commit()
    return it.id


@pytest.fixture
def new_event(organiser, coord, make_event):
    def _new(quantities=(), status="planning"):
        event_id = make_event(organiser, status=status, coordinator_id=coord)
        requirement_ids = []
        for quantity in quantities:
            req = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=quantity)
            db.session.add(req)
            db.session.commit()
            requirement_ids.append(req.id)
        return event_id, requirement_ids
    return _new


def _reserve(event_id, requirement_id, item_id, quantity):
    record = EquipmentReservation(
        event_id=event_id, equipment_requirement_id=requirement_id, equipment_item_id=item_id,
        quantity=quantity, start_datetime=START, end_datetime=END, status="reserved",
    )
    db.session.add(record)
    db.session.commit()
    return record.id


def _status(reservation_id):
    db.session.expire_all()
    return db.session.get(EquipmentReservation, reservation_id).status


def _free(client, path, headers, item_id):
    res = client.get(
        path("equipment.check_item_availability", item_id=item_id)
        + f"?start={START.isoformat()}&end={END.isoformat()}&quantity=1",
        headers=headers,
    )
    return res.get_json()["freeQuantity"]


def _release(client, path, headers, reservation_id):
    return client.post(path("equipment.release_equipment", reservation_id=reservation_id), headers=headers)


def test_tech_release_frees_the_quantity(client, path, tech, item, new_event):
    event_id, (req,) = new_event([4])
    reservation = _reserve(event_id, req, item, 4)
    assert _free(client, path, tech, item) == 6
    res = _release(client, path, tech, reservation)
    assert res.status_code == 200
    assert res.get_json()["status"] == "released"
    assert _free(client, path, tech, item) == 10


def test_released_reservation_is_kept_not_deleted(client, path, tech, item, new_event):
    event_id, (req,) = new_event([4])
    reservation = _reserve(event_id, req, item, 4)
    _release(client, path, tech, reservation)
    db.session.expire_all()
    assert EquipmentReservation.query.count() == 1
    assert _status(reservation) == "released"


def test_releasing_twice_returns_400_and_does_not_return_quantity_twice(client, path, tech, item, new_event):
    event_id, (req,) = new_event([4])
    reservation = _reserve(event_id, req, item, 4)
    assert _release(client, path, tech, reservation).status_code == 200
    second = _release(client, path, tech, reservation)
    assert second.status_code == 400
    assert _free(client, path, tech, item) == 10


def test_releasing_unknown_reservation_returns_404(client, path, tech):
    res = _release(client, path, tech, 99999)
    assert res.status_code == 404
    assert res.get_json()["error"] == "Reservation not found"


@pytest.mark.parametrize("email,role", [
    ("c65@test.com", "event_coordinator"),
    ("o65@test.com", "event_organiser"),
    ("a65@test.com", "attendee"),
])
def test_other_roles_cannot_release(client, path, make_user, auth_header, item, new_event, email, role):
    event_id, (req,) = new_event([4])
    reservation = _reserve(event_id, req, item, 4)
    make_user(email, [role])
    assert _release(client, path, auth_header(email), reservation).status_code == 403
    assert _status(reservation) == "reserved"


def test_unauthenticated_cannot_release(client, path, item, new_event):
    event_id, (req,) = new_event([4])
    reservation = _reserve(event_id, req, item, 4)
    assert _release(client, path, {}, reservation).status_code == 401
    assert _status(reservation) == "reserved"


def test_cancelling_an_event_releases_all_its_reservations(client, path, tech, coord_headers, item, new_event):
    event_id, (req_a, req_b) = new_event([3, 2])
    first = _reserve(event_id, req_a, item, 3)
    second = _reserve(event_id, req_b, item, 2)
    assert _free(client, path, tech, item) == 5
    res = client.post(
        path("events.cancel_event_route", event_id=event_id),
        json={"reason": REASON, "confirmed": True}, headers=coord_headers,
    )
    assert res.status_code == 200
    assert _status(first) == "released" and _status(second) == "released"
    assert EquipmentReservation.query.count() == 2
    assert _free(client, path, tech, item) == 10


def test_cancelling_via_status_endpoint_also_releases(client, path, tech, coord_headers, item, new_event):
    event_id, (req,) = new_event([4])
    reservation = _reserve(event_id, req, item, 4)
    res = client.post(
        path("events.change_event_status", event_id=event_id),
        json={"status": "cancelled", "reason": REASON}, headers=coord_headers,
    )
    assert res.status_code == 200
    assert _status(reservation) == "released"
    assert _free(client, path, tech, item) == 10


def test_cancelling_an_event_leaves_other_events_reservations_alone(client, path, coord_headers, item, new_event):
    event_a, (req_a,) = new_event([3])
    event_b, (req_b,) = new_event([2])
    reservation_a = _reserve(event_a, req_a, item, 3)
    reservation_b = _reserve(event_b, req_b, item, 2)
    client.post(
        path("events.cancel_event_route", event_id=event_a),
        json={"reason": REASON, "confirmed": True}, headers=coord_headers,
    )
    assert _status(reservation_a) == "released"
    assert _status(reservation_b) == "reserved"


def test_cancelling_an_event_with_no_reservations_succeeds(client, path, coord_headers, new_event):
    event_id, _ = new_event([])
    res = client.post(
        path("events.cancel_event_route", event_id=event_id),
        json={"reason": REASON, "confirmed": True}, headers=coord_headers,
    )
    assert res.status_code == 200
    assert EquipmentReservation.query.count() == 0


def test_removing_a_requirement_releases_only_its_reservation(client, path, tech, coord_headers, item, new_event):
    event_id, (req_a, req_b) = new_event([3, 2])
    removed = _reserve(event_id, req_a, item, 3)
    kept = _reserve(event_id, req_b, item, 2)
    res = client.put(
        path("events.update_event_route", event_id=event_id),
        json={
            "fields": {"equipment_requirements": [{"id": req_b, "type": "Projector", "quantity": 2}]},
            "offlineReviewConfirmed": True,
        },
        headers=coord_headers,
    )
    assert res.status_code == 200
    assert _status(removed) == "released"
    assert _status(kept) == "reserved"
    assert EquipmentReservation.query.count() == 2
    assert _free(client, path, tech, item) == 8


def test_released_units_are_free_for_another_event(client, path, tech, item, new_event):
    event_a, (req_a,) = new_event([10], status="approved")
    event_b, (req_b,) = new_event([3], status="approved")
    reservation = _reserve(event_a, req_a, item, 10)
    body = {
        "eventId": event_b, "requirementId": req_b, "equipmentItemId": item,
        "start": START.isoformat(), "end": END.isoformat(),
    }
    url = path("equipment.reserve_equipment")
    assert client.post(url, json=body, headers=tech).status_code == 400
    _release(client, path, tech, reservation)
    assert client.post(url, json=body, headers=tech).status_code == 201