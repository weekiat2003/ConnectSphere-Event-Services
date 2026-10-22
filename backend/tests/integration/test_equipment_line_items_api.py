from datetime import datetime

import pytest

from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import EventEquipmentRequirement, EventFieldEditLog

COORD = "coordinator@test.com"


@pytest.fixture
def event_id(organiser, coordinator, make_event):
    return make_event(organiser, status="approved", coordinator_id=coordinator)


def url(event_id):
    return f"/api/events/{event_id}/update"


def put(client, headers, event_id, requirements, confirmed=True):
    return client.put(
        url(event_id),
        json={"fields": {"equipment_requirements": requirements},
              "offlineReviewConfirmed": confirmed},
        headers=headers)


def saved(event_id):
    db.session.expire_all()
    return [(r.equipment_type, r.quantity) for r in
            EventEquipmentRequirement.query.filter_by(event_id=event_id)
            .order_by(EventEquipmentRequirement.id).all()]


def add_line(event_id, type_="Projector", quantity=2):
    line = EventEquipmentRequirement(event_id=event_id, equipment_type=type_, quantity=quantity)
    db.session.add(line)
    db.session.commit()
    return line


def test_coordinator_adds_a_line(client, auth_header, event_id):
    res = put(client, auth_header(COORD), event_id, [{"type": "Projector", "quantity": 2}])
    assert res.status_code == 200
    assert saved(event_id) == [("Projector", 2)]


def test_removing_a_reserved_line_releases_the_reservation(client, auth_header, event_id):
    keep = add_line(event_id, "Projector", 2)
    gone = add_line(event_id, "Microphone", 1)
    item = EquipmentItem(name="Microphone", total_quantity=10)
    db.session.add(item)
    db.session.commit()
    booking = EquipmentReservation(
        event_id=event_id, equipment_requirement_id=gone.id, equipment_item_id=item.id,
        quantity=1, start_datetime=datetime(2026, 12, 1, 10), end_datetime=datetime(2026, 12, 1, 11),
        status="reserved")
    db.session.add(booking)
    db.session.commit()
    booking_id = booking.id

    res = put(client, auth_header(COORD), event_id,
              [{"id": keep.id, "type": "Projector", "quantity": 2}])
    assert res.status_code == 200
    assert saved(event_id) == [("Projector", 2)]
    db.session.expire_all()
    assert db.session.get(EquipmentReservation, booking_id).status == "released"


def test_removing_a_line_without_a_reservation_works(client, auth_header, event_id):
    add_line(event_id)
    res = put(client, auth_header(COORD), event_id, [])
    assert res.status_code == 200
    assert saved(event_id) == []


def test_confirmed_event_returns_423_and_logs_the_attempt(client, auth_header, organiser, coordinator, make_event):
    locked_id = make_event(organiser, status="confirmed", coordinator_id=coordinator)
    add_line(locked_id)
    res = put(client, auth_header(COORD), locked_id, [])
    assert res.status_code == 423
    assert saved(locked_id) == [("Projector", 2)]
    log = EventFieldEditLog.query.filter_by(event_id=locked_id).one()
    assert log.was_rejected is True


def test_status_that_cannot_be_edited_returns_409_with_the_reason(client, auth_header, organiser, coordinator, make_event):
    early_id = make_event(organiser, status="submitted", coordinator_id=coordinator)
    res = put(client, auth_header(COORD), early_id, [{"type": "Projector", "quantity": 1}])
    assert res.status_code == 409
    assert "submitted" in res.get_json()["error"]


def test_missing_offline_review_confirmation_returns_400(client, auth_header, event_id):
    res = put(client, auth_header(COORD), event_id, [{"type": "Projector", "quantity": 1}], confirmed=False)
    assert res.status_code == 400
    assert saved(event_id) == []


@pytest.mark.parametrize("requirement, bad_key", [
    ({"type": "", "quantity": 1}, "type"),
    ({"type": "Projector", "quantity": 0}, "quantity"),
])
def test_bad_line_returns_400_naming_the_field(client, auth_header, event_id, requirement, bad_key):
    res = put(client, auth_header(COORD), event_id, [requirement])
    assert res.status_code == 400
    assert f"equipment_requirements[0].{bad_key}" in res.get_json()["errors"]
    assert saved(event_id) == []


def test_modification_is_recorded_in_the_edit_log(client, auth_header, event_id):
    line = add_line(event_id, "Microphone", 1)
    res = put(client, auth_header(COORD), event_id,
              [{"id": line.id, "type": "Microphone", "quantity": 1},
               {"type": "Projector", "quantity": 2}])
    assert res.status_code == 200
    log = EventFieldEditLog.query.filter_by(event_id=event_id).one()
    assert len(log.old_values["equipment_requirements"]) == 1
    assert len(log.new_values["equipment_requirements"]) == 2


def test_another_coordinator_gets_403(client, auth_header, make_user, event_id):
    make_user("other@test.com", ["event_coordinator"])
    res = put(client, auth_header("other@test.com"), event_id, [{"type": "Projector", "quantity": 1}])
    assert res.status_code == 403
    assert saved(event_id) == []